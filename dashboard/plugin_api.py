"""Finanzen plugin backend — BWA (DATEV KER) aus der nulleins Datenbank.

Liest data/bwa.db des nulleins-Repos (NUR lesend). Die KER-Logik ist ein
1:1 Port von lib/bwa.ts (computeBwa), damit beide Oberflächen identisch
rechnen. Routes mounten unter /api/plugins/finanzen/.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


async def _read_json(request: Request) -> dict:
    """Body tolerant lesen: Das Plugin-SDK sendet JSON teils doppelt kodiert
    (String statt Objekt) — beides akzeptieren."""
    import json as _json
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = _json.loads(raw)
    except Exception:
        raise HTTPException(400, "Body ist kein gültiges JSON")
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except Exception:
            raise HTTPException(400, "Body ist kein gültiges JSON")
    if not isinstance(data, dict):
        raise HTTPException(422, f"Body muss ein JSON-Objekt sein, nicht {type(data).__name__}")
    return data

# nulleins-Codebase: %USERPROFILE%\nullaufeins (Windows) bzw. ~/nullaufeins.
# Per Umgebungsvariable NULLEINS_HOME ueberschreibbar.
NULLEINS_HOME = Path(os.environ.get("NULLEINS_HOME", Path.home() / "nullaufeins"))
DEFAULT_DB = str(NULLEINS_HOME / "data" / "bwa.db")

# Schemata identisch zur nulleins-App (lib/bwa-store.ts, lib/invoice-store.ts),
# damit das Plugin auch OHNE nulleins-App eigenständig funktioniert.
BWA_SCHEMA = """
CREATE TABLE IF NOT EXISTS bwa_entries (
    month TEXT NOT NULL,
    field TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY (month, field)
);
"""

INVOICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    email_id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    subject TEXT NOT NULL,
    date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'email'
);
CREATE TABLE IF NOT EXISTS invoice_matches (
    invoice_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    payment_description TEXT NOT NULL,
    confidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_files (
    email_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL
);
"""

# Reihenfolge wie im KER-Blatt (lib/bwa.ts).
INPUT_FIELDS: list[tuple[str, str, str]] = [
    ("umsatz", "Umsatzerlöse", "Ertrag"),
    ("bestandsveraenderung", "Bestandsveränderung FE/UE", "Ertrag"),
    ("aktivierteEigenleistungen", "Aktivierte Eigenleistungen", "Ertrag"),
    ("material", "Material-/Wareneinkauf", "Einsatz"),
    ("sonstBetrErloese", "So. betr. Erlöse", "Ertrag"),
    ("personal", "Personalkosten", "Kostenarten"),
    ("raum", "Raumkosten", "Kostenarten"),
    ("betrSteuern", "Betriebliche Steuern", "Kostenarten"),
    ("versicherungen", "Versicherungen/Beiträge", "Kostenarten"),
    ("besondereKosten", "Besondere Kosten", "Kostenarten"),
    ("fahrzeug", "Fahrzeugkosten (ohne Steuer)", "Kostenarten"),
    ("werbungReise", "Werbe-/Reisekosten", "Kostenarten"),
    ("kostenWarenabgabe", "Kosten Warenabgabe", "Kostenarten"),
    ("abschreibungen", "Abschreibungen", "Kostenarten"),
    ("reparatur", "Reparatur/Instandhaltung", "Kostenarten"),
    ("sonstigeKosten", "Sonstige Kosten", "Kostenarten"),
    ("zinsaufwand", "Zinsaufwand", "Neutral"),
    ("sonstNeutralAufwand", "Sonstiger neutraler Aufwand", "Neutral"),
    ("zinsertraege", "Zinserträge", "Neutral"),
    ("sonstNeutralErtrag", "Sonstiger neutraler Ertrag", "Neutral"),
    ("verrechneteKalkKosten", "Verrechnete kalk. Kosten", "Neutral"),
    ("steuernEinkommenErtrag", "Steuern Einkommen u. Ertrag", "Steuern"),
]

KOSTEN_KEYS = [
    "personal", "raum", "betrSteuern", "versicherungen", "besondereKosten",
    "fahrzeug", "werbungReise", "kostenWarenabgabe", "abschreibungen",
    "reparatur", "sonstigeKosten",
]

KOSTENARTEN_LABELS = [
    ("material", "Material-/Wareneinkauf"),
    ("personal", "Personalkosten"),
    ("raum", "Raumkosten"),
    ("betrSteuern", "Betriebliche Steuern"),
    ("versicherungen", "Versicherungen/Beiträge"),
    ("besondereKosten", "Besondere Kosten"),
    ("fahrzeug", "Fahrzeugkosten (ohne Steuer)"),
    ("werbungReise", "Werbe-/Reisekosten"),
    ("kostenWarenabgabe", "Kosten Warenabgabe"),
    ("abschreibungen", "Abschreibungen"),
    ("reparatur", "Reparatur/Instandhaltung"),
    ("sonstigeKosten", "Sonstige Kosten"),
]

MONATE_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember"]

VALID_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
VALID_DATE = r"^\d{4}-\d{2}-\d{2}$"

_INPUT_KEYS = {k for k, _, _ in INPUT_FIELDS}


def _parse_german_number(raw) -> Optional[int]:
    """\"5.963,32\" / \"5963,32\" / \"100\" / \"-4.810,40\" -> Cent (None = keine Zahl)."""
    if isinstance(raw, (int, float)):
        return int(round(raw))
    if not isinstance(raw, str):
        return None
    t = raw.strip().replace("€", "").replace(" ", "").replace("\u00a0", "")
    if not t:
        return None
    if re.search(r",\d{1,2}$", t):
        normalized = t.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{1,2}$", t):
        normalized = t.replace(",", "")
    else:
        normalized = re.sub(r"[.,]", "", t)
    if not re.fullmatch(r"-?\d+(\.\d+)?", normalized):
        return None
    n = float(normalized)
    return int(round(n * 100)) if n == n and abs(n) != float("inf") else None


def _db_path() -> Path:
    path = Path(os.environ.get("NULLEINS_BWA_DB", DEFAULT_DB))
    if not path.exists():
        # Autonom betreiben: DB selbst anlegen, wenn keine nulleins-App vorhanden.
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
        con.executescript(BWA_SCHEMA)
        con.commit()
        con.close()
    return path


def _invoices_db_path() -> Path:
    path = Path(os.environ.get("NULLEINS_INVOICES_DB", NULLEINS_HOME / "data" / "invoices.db"))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
        con.executescript(INVOICES_SCHEMA)
        con.commit()
        con.close()
    return path


def _invoice_files_dir() -> Path:
    return Path(os.environ.get("NULLEINS_INVOICE_FILES", NULLEINS_HOME / "data" / "invoice-files"))


def _ensure_source_column(con: sqlite3.Connection) -> None:
    """Migration: Quellen-Spalte (email | telegram | upload), bestehende Zeilen = email."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(invoices)")}
    if "source" not in cols:
        con.execute("ALTER TABLE invoices ADD COLUMN source TEXT NOT NULL DEFAULT 'email'")
        con.commit()


SOURCES = ("email", "telegram", "upload")
SOURCES_DE = {"email": "E-Mail", "telegram": "Telegram", "upload": "Upload"}


def _load_month(cur: sqlite3.Cursor, month: str) -> dict[str, int]:
    rows = cur.execute(
        "SELECT field, amount_cents FROM bwa_entries WHERE month = ?", (month,)
    ).fetchall()
    return {field: int(cents) for field, cents in rows}


# --- Tageserfassung (daily_items) --------------------------------------------
# Solo-Unternehmer verdienen/tätigen Ausgaben täglich, oft mehrmals pro Tag.
# Jede Buchung ist eine eigene Zeile (Einnahme ODER Ausgabe, mit Bezeichnung
# und optionalem Bon/Kassenbon). Diese sammeln sich automatisch in der
# Monatsrechnung:
#   Einnahmen  -> umsatz (Umsatzerlöse)
#   Ausgaben   -> sonstigeKosten (Sonstige Kosten)

RECEIPT_DIR = Path(os.environ.get("NULLEINS_DAILY_RECEIPTS",
                                  NULLEINS_HOME / "data" / "daily-receipts"))
DAILY_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}


def _ensure_daily_tables(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS daily_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "date TEXT NOT NULL,"
        "kind TEXT NOT NULL CHECK (kind IN ('income','expense')),"
        "label TEXT NOT NULL DEFAULT '',"
        "amount_cents INTEGER NOT NULL DEFAULT 0,"
        "receipt_file TEXT,"
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # Migration: alte daily_entries (1 Zeile pro Tag) in Buchungen überführen.
    cols = {r[1] for r in con.execute("PRAGMA table_info(daily_entries)")}
    if cols:
        for row in con.execute(
            "SELECT date, income_cents, expense_cents, note FROM daily_entries"
        ).fetchall():
            date, income, expense, note = row
            note = (note or "").strip()
            if income:
                con.execute(
                    "INSERT INTO daily_items (date, kind, label, amount_cents) "
                    "VALUES (?, 'income', ?, ?)", (date, note or "Einnahme", int(income)))
            if expense:
                con.execute(
                    "INSERT INTO daily_items (date, kind, label, amount_cents) "
                    "VALUES (?, 'expense', ?, ?)", (date, note or "Ausgabe", int(expense)))
        con.execute("ALTER TABLE daily_entries RENAME TO daily_entries_migrated")
    con.commit()


def _bwa_conn() -> sqlite3.Connection:
    """bwa.db öffnen und Schema (bwa_entries + daily_items) sicherstellen."""
    con = sqlite3.connect(str(_db_path()))
    con.row_factory = sqlite3.Row
    con.executescript(BWA_SCHEMA)
    _ensure_daily_tables(con)
    return con


_daily_conn = _bwa_conn


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _daily_month_sums(cur: sqlite3.Cursor, month: str) -> tuple[int, int]:
    row = cur.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents ELSE 0 END),0) "
        "FROM daily_items WHERE date LIKE ?",
        (f"{month}-%",),
    ).fetchone()
    return int(row[0]), int(row[1])


def _merged_entries(cur: sqlite3.Cursor, month: str) -> dict[str, int]:
    """BWA-Monat + gesammelte Tagesbuchungen (in die Monatsrechnung rolliert)."""
    entries = _load_month(cur, month)
    income, expense = _daily_month_sums(cur, month)
    if income:
        entries["umsatz"] = entries.get("umsatz", 0) + income
    if expense:
        entries["sonstigeKosten"] = entries.get("sonstigeKosten", 0) + expense
    return entries


def _pct(part: float, whole: float) -> float:
    return (part / whole) * 100 if whole else 0.0


def _v(inputs: dict[str, int], key: str) -> int:
    val = inputs.get(key)
    return int(val) if isinstance(val, (int, float)) else 0


def compute_bwa(inputs: dict[str, int]) -> dict[str, float]:
    """Port von computeBwa (lib/bwa.ts). Alle Beträge in Cent."""
    gesamtleistung = (
        _v(inputs, "umsatz")
        + _v(inputs, "bestandsveraenderung")
        + _v(inputs, "aktivierteEigenleistungen")
    )
    material = _v(inputs, "material")
    rohertrag = gesamtleistung - material
    betrieblicher_rohertrag = rohertrag + _v(inputs, "sonstBetrErloese")
    gesamtkosten = sum(_v(inputs, k) for k in KOSTEN_KEYS)
    betriebsergebnis = betrieblicher_rohertrag - gesamtkosten
    neutraler_aufwand = _v(inputs, "zinsaufwand") + _v(inputs, "sonstNeutralAufwand")
    neutraler_ertrag = (
        _v(inputs, "zinsertraege")
        + _v(inputs, "sonstNeutralErtrag")
        + _v(inputs, "verrechneteKalkKosten")
    )
    ergebnis_vor_steuern = betriebsergebnis - neutraler_aufwand + neutraler_ertrag
    vorlaeufiges_ergebnis = ergebnis_vor_steuern - _v(inputs, "steuernEinkommenErtrag")
    return {
        "gesamtleistung": gesamtleistung,
        "rohertrag": rohertrag,
        "betrieblicherRohertrag": betrieblicher_rohertrag,
        "gesamtkosten": gesamtkosten,
        "betriebsergebnis": betriebsergebnis,
        "neutralerAufwand": neutraler_aufwand,
        "neutralerErtrag": neutraler_ertrag,
        "ergebnisVorSteuern": ergebnis_vor_steuern,
        "vorlaeufigesErgebnis": vorlaeufiges_ergebnis,
        "pctMaterialGesLeistung": round(_pct(material, gesamtleistung), 1),
        "pctPersonalGesKosten": round(_pct(_v(inputs, "personal"), gesamtkosten), 1),
        "aufschlagMaterial": round(_pct(rohertrag, material), 1),
    }


def cost_categories(inputs: dict[str, int]) -> list[dict]:
    cats = [
        {"category": label, "total": _v(inputs, key)}
        for key, label in KOSTENARTEN_LABELS
    ]
    cats = [c for c in cats if c["total"] != 0]
    cats.sort(key=lambda c: -c["total"])
    return cats


def month_label_de(month: str) -> str:
    y, m = month.split("-")
    return f"{MONATE_DE[int(m) - 1]} {y}"


def _all_months(cur: sqlite3.Cursor) -> list[str]:
    """Monate mit BWA-Werten ODER Tagesbuchungen."""
    rows = cur.execute(
        "SELECT month FROM bwa_entries UNION "
        "SELECT DISTINCT substr(date, 1, 7) FROM daily_items ORDER BY 1").fetchall()
    return [r[0] for r in rows if r[0]]


@router.get("/overview")
async def overview(month: Optional[str] = Query(None)):
    """Monat + Jahresübersicht in einem Aufruf (alles Cent)."""
    target = month or _current_month()
    if not re.match(VALID_MONTH, target):
        raise HTTPException(400, f"Ungültiger Monat: {target}")
    con = _bwa_conn()
    try:
        cur = con.cursor()
        months = _all_months(cur)

        entries = _merged_entries(cur, target)
        manual_entries = _load_month(cur, target)
        result = compute_bwa(entries)
        year = target[:4]
        year_months = [m for m in months if m.startswith(year)]
        jahreszeilen = []
        for m in year_months:
            e = _merged_entries(cur, m)
            r = compute_bwa(e)
            jahreszeilen.append({
                "month": m,
                "label": month_label_de(m),
                "umsatz": _v(e, "umsatz"),
                "gesamtkosten": r["gesamtkosten"],
                "betriebsergebnis": r["betriebsergebnis"],
                "vorlaeufigesErgebnis": r["vorlaeufigesErgebnis"],
            })
        jahressumme = compute_bwa(_merged_year(cur, year))
        daily_income, daily_expense = _daily_month_sums(cur, target)
        return {
            "month": target,
            "monthLabel": month_label_de(target),
            "months": months,
            "fields": [
                {"key": k, "label": label, "group": group,
                 "value": entries.get(k), "manualValue": manual_entries.get(k)}
                for k, label, group in INPUT_FIELDS
            ],
            "daily": {
                "incomeCents": daily_income,
                "expenseCents": daily_expense,
                "netCents": daily_income - daily_expense,
            },
            "result": result,
            "costCategories": cost_categories(entries),
            "year": year,
            "yearMonths": jahreszeilen,
            "yearResult": jahressumme,
        }
    finally:
        con.close()


@router.post("/overview")
async def save_overview(request: Request):
    """BWA-Monat speichern: {month: "YYYY-MM", entries: {feld: "5.963,32" | Cent}}.
    Schreibt die bwa_entries-Tabelle derselben Datenbank, die nulleins liest."""
    body = await _read_json(request)
    month = body.get("month")
    if not isinstance(month, str) or not re.match(VALID_MONTH, month):
        raise HTTPException(400, f"Ungültiger Monat: {month!r}")
    raw_entries = body.get("entries")
    if not isinstance(raw_entries, dict):
        raise HTTPException(400, "entries muss ein Objekt sein")
    unknown = [k for k in raw_entries if k not in _INPUT_KEYS]
    if unknown:
        raise HTTPException(400, f"Unbekannte Felder: {unknown}")

    updates: dict[str, int] = {}
    for key, value in raw_entries.items():
        cents = _parse_german_number(value)
        if cents is None:
            continue  # leer/unparsbar = kein Eintrag (wie in nulleins)
        updates[key] = cents

    con = _bwa_conn()
    try:
        with con:
            # Doppelzählung verhindern: Die UI zeigt manuelle BWA + Tagesbuchungen
            # zusammen. Beim Speichern der Monatsrechnung die Tagesanteile wieder
            # abziehen, damit daily_items nicht doppelt in bwa_entries landen.
            cur = con.cursor()
            daily_income, daily_expense = _daily_month_sums(cur, month)
            if daily_income and "umsatz" in updates:
                updates["umsatz"] = max(0, updates["umsatz"] - daily_income)
            if daily_expense and "sonstigeKosten" in updates:
                updates["sonstigeKosten"] = max(0, updates["sonstigeKosten"] - daily_expense)
            for field, cents in updates.items():
                con.execute(
                    "INSERT INTO bwa_entries (month, field, amount_cents) VALUES (?, ?, ?) "
                    "ON CONFLICT (month, field) DO UPDATE SET amount_cents = excluded.amount_cents",
                    (month, field, cents),
                )
        cur = con.cursor()
        saved_entries = _load_month(cur, month)
        saved_months = _all_months(cur)
    finally:
        con.close()

    return {
        "ok": True,
        "month": month,
        "monthLabel": month_label_de(month),
        "months": saved_months,
        "entries": saved_entries,
        "result": compute_bwa(saved_entries),
        "costCategories": cost_categories(saved_entries),
        "saved": len(updates),
    }


# --- Tageserfassung: Endpunkte ------------------------------------------------

def _row_to_item(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "date": r["date"],
        "kind": r["kind"],
        "label": r["label"],
        "amountCents": r["amount_cents"],
        "hasReceipt": bool(r["receipt_file"]),
    }


@router.get("/daily")
async def daily_list(month: Optional[str] = Query(None)):
    """Tagesbuchungen eines Monats (YYYY-MM) + Summen. Ohne month: aktueller Monat."""
    from datetime import date as date_cls
    today = date_cls.today().isoformat()
    target = month if month else today[:7]
    if not re.match(VALID_MONTH, target):
        raise HTTPException(400, f"Ungültiger Monat: {target}")
    con = _daily_conn()
    try:
        cur = con.cursor()
        items = [
            _row_to_item(r) for r in cur.execute(
                "SELECT * FROM daily_items WHERE date LIKE ? ORDER BY date DESC, id DESC",
                (f"{target}-%",),
            )
        ]
        # Pro Tag aggregiert (für Diagramm + Listenköpfe).
        agg: dict[str, dict] = {}
        for it in items:
            d = agg.setdefault(it["date"], {"date": it["date"], "incomeCents": 0,
                                            "expenseCents": 0, "netCents": 0, "items": []})
            if it["kind"] == "income":
                d["incomeCents"] += it["amountCents"]
            else:
                d["expenseCents"] += it["amountCents"]
            d["netCents"] = d["incomeCents"] - d["expenseCents"]
            d["items"].append(it)
        days = sorted(agg.values(), key=lambda d: d["date"], reverse=True)
        month_income, month_expense = _daily_month_sums(cur, target)
        row = cur.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents ELSE 0 END),0) "
            "FROM daily_items WHERE date <= ? AND date LIKE ?",
            (today, f"{target}-%"),
        ).fetchone()
        mtd_income, mtd_expense = int(row[0]), int(row[1])
        months = [r2[0] for r2 in cur.execute(
            "SELECT DISTINCT substr(date,1,7) AS m FROM daily_items ORDER BY m"
        ).fetchall()]
        return {
            "month": target,
            "monthLabel": month_label_de(target),
            "months": months,
            "today": today,
            "items": items,
            "days": days,
            "monthTotals": {
                "incomeCents": month_income,
                "expenseCents": month_expense,
                "netCents": month_income - month_expense,
            },
            "monthToDate": {
                "incomeCents": mtd_income,
                "expenseCents": mtd_expense,
                "netCents": mtd_income - mtd_expense,
            },
        }
    finally:
        con.close()


@router.post("/daily/item")
async def daily_item_add(request: Request):
    """Neue Tagesbuchung: {date? (YYYY-MM-DD, Default heute),
    kind ('expense'|'income'), label, amount ("4,50" | Cent),
    receiptBase64?, receiptName? (Bon/Kassenbon)}. Mehrere pro Tag möglich."""
    body = await _read_json(request)
    from datetime import date as date_cls
    date = str(body.get("date") or date_cls.today().isoformat())
    if not re.match(VALID_DATE, date):
        raise HTTPException(400, f"Ungültiges Datum: {date!r} (JJJJ-MM-TT erwartet)")
    kind = str(body.get("kind") or "expense")
    if kind not in ("income", "expense"):
        raise HTTPException(400, "kind muss 'income' oder 'expense' sein")
    amount = _parse_german_number(body.get("amount"))
    if amount is None or amount <= 0:
        raise HTTPException(400, f"Ungültiger Betrag: {body.get('amount')!r}")
    label = str(body.get("label") or "").strip()[:120]
    receipt_file = None
    raw = body.get("receiptBase64")
    if raw:
        import base64 as b64
        try:
            data = b64.b64decode(raw, validate=True)
        except Exception:
            raise HTTPException(400, "receiptBase64 ist kein gültiges Base64")
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "Bon zu groß (max 20 MB)")
        RECEIPT_DIR.mkdir(parents=True, exist_ok=True)

    con = _daily_conn()
    try:
        with con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO daily_items (date, kind, label, amount_cents) VALUES (?, ?, ?, ?)",
                (date, kind, label, amount),
            )
            item_id = cur.lastrowid
            if raw:
                ext = Path(str(body.get("receiptName") or "bon.jpg")).suffix.lower()
                if ext not in DAILY_MIME:
                    ext = ".jpg"
                receipt_file = f"{item_id}{ext}"
                (RECEIPT_DIR / receipt_file).write_bytes(data)
                cur.execute("UPDATE daily_items SET receipt_file = ? WHERE id = ?",
                            (receipt_file, item_id))
        cur = con.cursor()
        r = cur.execute("SELECT * FROM daily_items WHERE id = ?", (item_id,)).fetchone()
        mi, me = _daily_month_sums(cur, date[:7])
        return {
            "ok": True,
            "item": _row_to_item(r),
            "monthTotals": {"incomeCents": mi, "expenseCents": me, "netCents": mi - me},
        }
    finally:
        con.close()


@router.get("/daily/item/{item_id}/receipt")
async def daily_item_receipt(item_id: int):
    """Bon/Kassenbon einer Buchung (base64 eingebettet)."""
    con = _daily_conn()
    try:
        r = con.execute("SELECT receipt_file FROM daily_items WHERE id = ?", (item_id,)).fetchone()
    finally:
        con.close()
    if r is None:
        raise HTTPException(404, "Buchung nicht gefunden")
    if not r["receipt_file"]:
        raise HTTPException(404, "Kein Bon hinterlegt")
    path = RECEIPT_DIR / r["receipt_file"]
    if not path.exists():
        raise HTTPException(404, "Bon-Datei fehlt")
    mime = DAILY_MIME.get(path.suffix.lower(), "application/octet-stream")
    import base64 as b64
    return {"mimeType": mime, "base64": b64.b64encode(path.read_bytes()).decode("ascii")}


@router.delete("/daily/item/{item_id}")
async def daily_item_delete(item_id: int):
    """Tagesbuchung entfernen (Bon-Datei wird mitgelöscht)."""
    con = _daily_conn()
    try:
        with con:
            r = con.execute("SELECT receipt_file, date FROM daily_items WHERE id = ?",
                            (item_id,)).fetchone()
            if r is None:
                raise HTTPException(404, "Buchung nicht gefunden")
            con.execute("DELETE FROM daily_items WHERE id = ?", (item_id,))
        receipt_file = r["receipt_file"]
        cur = con.cursor()
        mi, me = _daily_month_sums(cur, r["date"][:7])
    finally:
        con.close()
    if receipt_file:
        path = RECEIPT_DIR / receipt_file
        if path.exists():
            path.unlink()
    return {"ok": True, "monthTotals": {"incomeCents": mi, "expenseCents": me, "netCents": mi - me}}


def _merged_year(cur: sqlite3.Cursor, year: str) -> dict[str, int]:
    merged: dict[str, int] = {}
    for field, cents in cur.execute(
        "SELECT field, amount_cents FROM bwa_entries WHERE month LIKE ?",
        (f"{year}-%",),
    ):
        merged[field] = merged.get(field, 0) + int(cents)
    # Tagesbuchungen des Jahres einrollen (umsatz / sonstigeKosten).
    row = cur.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents ELSE 0 END),0) "
        "FROM daily_items WHERE date LIKE ?",
        (f"{year}-%",),
    ).fetchone()
    if row[0]:
        merged["umsatz"] = merged.get("umsatz", 0) + int(row[0])
    if row[1]:
        merged["sonstigeKosten"] = merged.get("sonstigeKosten", 0) + int(row[1])
    return merged


# --- Rechnungen -------------------------------------------------------------

def _invoice_conn():
    path = _invoices_db_path()
    if not path.exists():
        raise HTTPException(404, f"Rechnungs-Datenbank nicht gefunden: {path}")
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(INVOICES_SCHEMA)
    _ensure_source_column(con)
    return con


def _row_to_invoice(r: sqlite3.Row) -> dict:
    source = r["source"] if "source" in r.keys() else "email"
    return {
        "id": r["email_id"],
        "vendor": r["vendor"],
        "subject": r["subject"],
        "date": r["date"],
        "amountCents": r["amount_cents"],
        "currency": r["currency"],
        "category": r["category"],
        "source": source,
        "sourceLabel": SOURCES_DE.get(source, source),
    }


def _has_pdf(invoice_id: str) -> bool:
    con = _invoice_conn()
    try:
        row = con.execute(
            "SELECT filename FROM invoice_files WHERE email_id = ?", (invoice_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return False
    return (_invoice_files_dir() / row["filename"]).exists()


def _pdf_base64(invoice_id: str) -> Optional[str]:
    con = _invoice_conn()
    try:
        row = con.execute(
            "SELECT filename FROM invoice_files WHERE email_id = ?", (invoice_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    path = _invoice_files_dir() / row["filename"]
    if not path.exists():
        return None
    import base64
    return base64.b64encode(path.read_bytes()).decode("ascii")


@router.get("/invoices")
async def invoices(source: Optional[str] = Query(None), q: Optional[str] = Query(None)):
    """Rechnungsliste, filterbar nach Quelle und Freitext (Lieferant/Betreff/Kategorie)."""
    con = _invoice_conn()
    try:
        sql = "SELECT * FROM invoices"
        where, params = [], []
        if source:
            where.append("source = ?")
            params.append(source)
        if q:
            where.append("(vendor LIKE ? OR subject LIKE ? OR category LIKE ?)")
            like = f"%{q}%"
            params += [like, like, like]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date DESC"
        rows = [ _row_to_invoice(r) for r in con.execute(sql, params) ]
        matched = {r2["invoice_id"] for r2 in con.execute("SELECT invoice_id FROM invoice_matches")}
        for row in rows:
            row["paymentMatch"] = row["id"] in matched
            f = con.execute(
                "SELECT filename FROM invoice_files WHERE email_id = ?", (row["id"],)
            ).fetchone()
            row["hasPdf"] = bool(f) and (_invoice_files_dir() / f["filename"]).exists()
        counts = {s: 0 for s in SOURCES}
        for r2 in con.execute("SELECT source, COUNT(*) c FROM invoices GROUP BY source"):
            counts[r2["source"]] = r2["c"]
        return {"invoices": rows, "counts": counts}
    finally:
        con.close()


@router.get("/invoices/{invoice_id}")
async def invoice_detail(invoice_id: str, pdf: bool = Query(False)):
    """Detail einer Rechnung; pdf=1 liefert das PDF base64 eingebettet."""
    con = _invoice_conn()
    try:
        r = con.execute("SELECT * FROM invoices WHERE email_id = ?", (invoice_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "Rechnung nicht gefunden")
        detail = _row_to_invoice(r)
        match = con.execute(
            "SELECT payment_date, payment_description, confidence FROM invoice_matches WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        detail["payment"] = dict(match) if match else None
        detail["filename"] = None
        detail["mimeType"] = "application/pdf"
        detail["filePath"] = None
        f = con.execute(
            "SELECT filename FROM invoice_files WHERE email_id = ?", (invoice_id,)
        ).fetchone()
        if f:
            detail["filename"] = f["filename"]
            detail["filePath"] = str(_invoice_files_dir() / f["filename"])
            if f["filename"].lower().endswith((".jpg", ".jpeg")):
                detail["mimeType"] = "image/jpeg"
            elif f["filename"].lower().endswith(".png"):
                detail["mimeType"] = "image/png"
            elif f["filename"].lower().endswith(".webp"):
                detail["mimeType"] = "image/webp"
        if pdf:
            detail["pdfBase64"] = _pdf_base64(invoice_id)
        return detail
    finally:
        con.close()


def _insert_invoice(con: sqlite3.Connection, *, source: str, filename: str,
                    vendor: str, subject: str, date: str,
                    amount_cents: int, currency: str, category: str,
                    pdf_bytes: bytes) -> dict:
    import uuid
    inv_id = uuid.uuid4().hex
    files_dir = _invoice_files_dir()
    files_dir.mkdir(parents=True, exist_ok=True)
    if pdf_bytes:
        suffix = Path(filename).suffix.lower()
        if suffix not in (".pdf", ".jpg", ".jpeg", ".png", ".webp"):
            suffix = ".pdf"
        (files_dir / f"{inv_id}{suffix}").write_bytes(pdf_bytes)
        con.execute(
            "INSERT INTO invoice_files (email_id, filename) VALUES (?, ?)",
            (inv_id, f"{inv_id}{suffix}"),
        )
    con.execute(
        "INSERT INTO invoices (email_id, vendor, subject, date, amount_cents, currency, category, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (inv_id, vendor, subject, date, amount_cents, currency, category, source),
    )
    con.commit()
    return {"id": inv_id}


@router.patch("/invoices/{invoice_id}")
async def invoice_update(invoice_id: str, request: Request):
    """Metadaten korrigieren. Editierbar: vendor, subject, date, amountCents,
    currency, category, source. Optional payment: {payment_date,
    payment_description} setzt/aktualisiert die Zuordnung (confidence=manual),
    payment: null entfernt sie."""
    editable = {"vendor": "vendor", "subject": "subject", "date": "date",
                "amountCents": "amount_cents", "currency": "currency",
                "category": "category", "source": "source"}
    body = await _read_json(request)
    con = _invoice_conn()
    try:
        r = con.execute("SELECT email_id FROM invoices WHERE email_id = ?", (invoice_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "Rechnung nicht gefunden")
        updates, params = [], []
        for key, col in editable.items():
            if key in body:
                val = body[key]
                if key == "amountCents":
                    val = int(val or 0)
                else:
                    val = str(val or "").strip()
                    if not val:
                        continue
                    if key == "source" and val not in SOURCES:
                        raise HTTPException(400, f"source muss einer von {SOURCES} sein")
                updates.append(f"{col} = ?")
                params.append(val)
        if updates:
            with con:
                con.execute(f"UPDATE invoices SET {', '.join(updates)} WHERE email_id = ?",
                            (*params, invoice_id))
        if "payment" in body:
            payment = body["payment"]
            with con:
                if payment is None:
                    con.execute("DELETE FROM invoice_matches WHERE invoice_id = ?", (invoice_id,))
                else:
                    con.execute(
                        "INSERT INTO invoice_matches (invoice_id, payment_id, payment_date, payment_description, confidence) "
                        "VALUES (?, ?, ?, ?, 'manual') "
                        "ON CONFLICT (invoice_id) DO UPDATE SET payment_date = excluded.payment_date, "
                        "payment_description = excluded.payment_description, confidence = 'manual'",
                        (invoice_id, f"manual-{invoice_id[:12]}",
                         str(payment.get("payment_date") or datetime.now().strftime("%Y-%m-%d")),
                         str(payment.get("payment_description") or "")[:300]),
                    )
        con2 = _invoice_conn()
        try:
            row = con2.execute("SELECT * FROM invoices WHERE email_id = ?", (invoice_id,)).fetchone()
            detail = _row_to_invoice(row)
            m = con2.execute(
                "SELECT payment_date, payment_description, confidence FROM invoice_matches WHERE invoice_id = ?",
                (invoice_id,)).fetchone()
            detail["payment"] = dict(m) if m else None
            return {"ok": True, "invoice": detail}
        finally:
            con2.close()
    finally:
        con.close()


@router.delete("/invoices/{invoice_id}")
async def invoice_delete(invoice_id: str):
    """Rechnung entfernen: Zeile + PDF-Datei löschen."""
    con = _invoice_conn()
    try:
        r = con.execute("SELECT email_id FROM invoices WHERE email_id = ?", (invoice_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "Rechnung nicht gefunden")
        f = con.execute(
            "SELECT filename FROM invoice_files WHERE email_id = ?", (invoice_id,)
        ).fetchone()
        with con:
            con.execute("DELETE FROM invoices WHERE email_id = ?", (invoice_id,))
            con.execute("DELETE FROM invoice_files WHERE email_id = ?", (invoice_id,))
            con.execute("DELETE FROM invoice_matches WHERE invoice_id = ?", (invoice_id,))
    finally:
        con.close()
    if f:
        path = _invoice_files_dir() / f["filename"]
        if path.exists():
            path.unlink()
    return {"ok": True}


# --- Report-Tabellen (SuSa / OPOS / Vorjahresvergleich / Vorschläge) ---------
import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_db  # noqa: E402

# LLM-Kategorie -> Standard-DATEV-Konto (im Bestätigungsdialog frei wählbar)
KATEGORIE_KONTO = {
    "Material": "5300",
    "Raum": "6310",
    "Versicherung": "6400",
    "Personal": "6010",
    "Fahrzeug": "6850",
    "Werbung": "6850",
    "Software": "6850",
    "Sonstiges": "6850",
}

BLATT_OF_KONTO = {"0": 1, "1": 1, "2": 1, "3": 2, "4": 2, "5": 2, "6": 3, "7": 3, "9": 3}

# Rechtsform-/Füllwörter, die beim Vergleich von Lieferantennamen stören.
_VENDOR_STOPWORDS = ("gmbh & co. kg", "gmbh & co kg", "gmbh", "kg", "ag", "ohg", "ug",
                     "e. k.", "ek", "s.r.l", "srl", "s.p.a", "spa", "bv", "ltd", "inc",
                     "llc", "e.k.", "inh.", "oHG")


def _vendor_norm(name: str) -> str:
    t = (name or "").lower().strip()
    t = re.sub(r"[^\wäöüß&.\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    for w in sorted(_VENDOR_STOPWORDS, key=len, reverse=True):
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _learn_vendor_account(rep, vendor: str, konto: str) -> None:
    """Bestätigte Buchung merken: Lieferant -> Konto (hit-Zähler erhöhen)."""
    norm = _vendor_norm(vendor)
    if not norm or not konto:
        return
    with rep:
        rep.execute(
            "INSERT INTO vendor_accounts (vendor_norm, vendor, konto) VALUES (?,?,?) "
            "ON CONFLICT (vendor_norm) DO UPDATE SET "
            "konto = excluded.konto, hits = hits + 1, last_used = datetime('now')",
            (norm, (vendor or "")[:120], konto))


def _learned_konto(rep, vendor: str) -> Optional[tuple]:
    """(konto, hits) der gelernten Zuordnung, falls vorhanden. Fuzzy:
    exakter Norm-Treffer, sonst längster beidseitiger Präfix-Schnitt."""
    norm = _vendor_norm(vendor)
    if not norm:
        return None
    row = rep.execute("SELECT konto, hits FROM vendor_accounts WHERE vendor_norm = ?",
                      (norm,)).fetchone()
    if row:
        return row["konto"], row["hits"]
    best = None
    for r in rep.execute("SELECT vendor_norm, konto, hits FROM vendor_accounts"):
        a, b = norm, r["vendor_norm"]
        # beidseitige Token-Schnitt als schwacher Treffer (>= 2 Token oder 1 langes Token)
        ta, tb = set(a.split()), set(b.split())
        common = ta & tb
        if common and (len(common) >= 2 or any(len(t) >= 5 for t in common)):
            if best is None or len(common) > best[2]:
                best = (r["konto"], r["hits"], len(common))
    if best:
        return best[0], best[1]
    return None


def _report_conn():
    return report_db.connect()


def _pick_month(requested: Optional[str], months: list[str]) -> str:
    """Gewünschter Monat (falls gültig), sonst aktueller Monat."""
    if requested and re.fullmatch(VALID_MONTH, requested):
        return requested
    return _current_month()


def _konto_meta(konto: str, cur) -> tuple[int, str]:
    """(blatt, beschriftung) zu einer Kontonummer — aus bestehenden Zeilen oder Fallback."""
    r = cur.execute(
        "SELECT blatt, beschriftung FROM susa_entries WHERE konto = ? "
        "ORDER BY month DESC LIMIT 1", (konto,)).fetchone()
    if r:
        return int(r["blatt"]), r["beschriftung"]
    is_kred = len(konto) >= 5 and konto.startswith("7")
    blatt = 4 if is_kred else BLATT_OF_KONTO.get(konto[:1], 3)
    return blatt, ""


def _susa_response(con, month: str) -> list[dict]:
    cur = con.cursor()
    rows = cur.execute(
        "SELECT * FROM susa_entries WHERE month = ? ORDER BY blatt, "
        "CAST(konto AS INTEGER), konto", (month,)).fetchall()
    entries = [dict(r) for r in rows]
    # Klassensummen + Gesamtsumme berechnen (wie DATEV-Ausdruck)
    groups: dict[tuple, dict] = {}
    for e in entries:
        is_kred = bool(e["is_kreditor"])
        klasse = "Gruppe 7" if is_kred else f"Klasse {min(int(e['konto']) // 1000, 9)}"
        blatt = 4 if is_kred else e["blatt"]
        key = (blatt, klasse)
        g = groups.setdefault(key, {"konto": "", "beschriftung": f"Summe {klasse}",
                                    "eb_wert": 0, "soll_monat": 0, "haben_monat": 0,
                                    "soll_kum": 0, "haben_kum": 0, "is_sum": True})
        g["eb_wert"] += e["eb_wert"] * (1 if e["eb_sh"] == "S" else -1)
        for f in ("soll_monat", "haben_monat", "soll_kum", "haben_kum"):
            g[f] += e[f]
    out = []
    by_blatt: dict[int, list] = {}
    for e in entries:
        by_blatt.setdefault(e["blatt"], []).append({**e, "is_sum": False})
    for blatt in sorted(by_blatt):
        out.extend(by_blatt[blatt])
        for (b, klasse), g in sorted(groups.items()):
            if b == blatt:
                out.append({**g, "blatt": b, "month": month, "id": None,
                            "eb_sh": "S", "saldo_sh": "S", "is_kreditor": blatt == 4})
    return out


@router.get("/report/susa")
async def report_susa(month: Optional[str] = Query(None)):
    con = _report_conn()
    try:
        cur = con.cursor()
        months = [r["month"] for r in cur.execute(
            "SELECT DISTINCT month FROM susa_entries ORDER BY month")]
        m = _pick_month(month, months)
        return {"month": m, "months": months, "entries": _susa_response(con, m)}
    finally:
        con.close()


@router.post("/report/susa")
async def report_susa_add(request: Request):
    body = await _read_json(request)
    month = str(body.get("month") or "")[:7]
    konto = str(body.get("konto") or "").strip()
    if not re.fullmatch(VALID_MONTH, month) or not konto:
        raise HTTPException(400, "month (YYYY-MM) und konto sind Pflicht")
    con = _report_conn()
    try:
        cur = con.cursor()
        blatt, beschrift = _konto_meta(konto, cur)
        is_kred = 1 if body.get("isKreditor") is not None else (1 if len(konto) >= 5 and konto.startswith("7") else 0)
        with con:
            cid = cur.execute(
                "INSERT INTO susa_entries (month, blatt, konto, beschriftung, eb_wert, "
                "eb_sh, soll_monat, haben_monat, soll_kum, haben_kum, saldo_sh, is_kreditor, invoice_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (month, blatt, konto, str(body.get("beschriftung") or beschrift),
                 float(body.get("ebWert") or 0), str(body.get("ebSh") or "S")[:1],
                 float(body.get("sollMonat") or 0), float(body.get("habenMonat") or 0),
                 float(body.get("sollKum") or 0), float(body.get("habenKum") or 0),
                 str(body.get("saldoSh") or "S")[:1], is_kred, body.get("invoiceId"))).lastrowid
        return {"ok": True, "id": cid}
    finally:
        con.close()


SUSA_EDITABLE = {"konto", "beschriftung", "eb_wert", "eb_sh", "soll_monat",
                 "haben_monat", "soll_kum", "haben_kum", "saldo_sh"}


@router.patch("/report/susa/{row_id}")
async def report_susa_update(row_id: int, request: Request):
    body = await _read_json(request)
    updates, params = [], []
    for key, col in (("konto", "konto"), ("beschriftung", "beschriftung"),
                     ("ebWert", "eb_wert"), ("ebSh", "eb_sh"),
                     ("sollMonat", "soll_monat"), ("habenMonat", "haben_monat"),
                     ("sollKum", "soll_kum"), ("habenKum", "haben_kum"),
                     ("saldoSh", "saldo_sh")):
        if key in body:
            val = body[key]
            if col in ("konto", "beschriftung", "eb_sh", "saldo_sh"):
                val = str(val or "").strip()
                if not val:
                    continue
            else:
                val = float(val or 0)
            updates.append(f"{col} = ?")
            params.append(val)
    if not updates:
        return {"ok": True}
    con = _report_conn()
    try:
        with con:
            con.execute(f"UPDATE susa_entries SET {', '.join(updates)} WHERE id = ?",
                        (*params, row_id))
        return {"ok": True}
    finally:
        con.close()


@router.delete("/report/susa/{row_id}")
async def report_susa_delete(row_id: int):
    con = _report_conn()
    try:
        with con:
            con.execute("DELETE FROM susa_entries WHERE id = ?", (row_id,))
        return {"ok": True}
    finally:
        con.close()


@router.get("/report/opos")
async def report_opos(month: Optional[str] = Query(None)):
    con = _report_conn()
    try:
        cur = con.cursor()
        months = [r["month"] for r in cur.execute(
            "SELECT DISTINCT month FROM opos_entries ORDER BY month")]
        m = _pick_month(month, months)
        rows = [dict(r) for r in cur.execute(
            "SELECT * FROM opos_entries WHERE month = ? ORDER BY datum, id", (m,))]
        return {"month": m, "months": months, "entries": rows}
    finally:
        con.close()


@router.post("/report/opos")
async def report_opos_add(request: Request):
    body = await _read_json(request)
    month = str(body.get("month") or "")[:7]
    if not re.fullmatch(VALID_MONTH, month):
        raise HTTPException(400, "month (YYYY-MM) ist Pflicht")
    con = _report_conn()
    try:
        with con:
            cid = con.execute(
                "INSERT INTO opos_entries (month, konto, beschriftung, rechnungs_nr, "
                "datum, faelligkeit, betrag, buchungstext, invoice_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (month, str(body.get("konto") or ""), str(body.get("beschriftung") or ""),
                 str(body.get("rechnungsNr") or ""), str(body.get("datum") or ""),
                 str(body.get("faelligkeit") or ""), float(body.get("betrag") or 0),
                 str(body.get("buchungstext") or ""), body.get("invoiceId"))).lastrowid
        return {"ok": True, "id": cid}
    finally:
        con.close()


OPOS_EDITABLE = {"konto": "konto", "beschriftung": "beschriftung",
                 "rechnungsNr": "rechnungs_nr", "datum": "datum",
                 "faelligkeit": "faelligkeit", "betrag": "betrag",
                 "buchungstext": "buchungstext"}


@router.patch("/report/opos/{row_id}")
async def report_opos_update(row_id: int, request: Request):
    body = await _read_json(request)
    updates, params = [], []
    for key, col in OPOS_EDITABLE.items():
        if key in body:
            if col == "betrag":
                updates.append(f"{col} = ?")
                params.append(float(body[key] or 0))
            else:
                val = str(body[key] or "").strip()
                updates.append(f"{col} = ?")
                params.append(val)
    if not updates:
        return {"ok": True}
    con = _report_conn()
    try:
        with con:
            con.execute(f"UPDATE opos_entries SET {', '.join(updates)} WHERE id = ?",
                        (*params, row_id))
        return {"ok": True}
    finally:
        con.close()


@router.delete("/report/opos/{row_id}")
async def report_opos_delete(row_id: int):
    con = _report_conn()
    try:
        with con:
            con.execute("DELETE FROM opos_entries WHERE id = ?", (row_id,))
        return {"ok": True}
    finally:
        con.close()


@router.get("/report/vv")
async def report_vv(month: str = Query(...)):
    """Vorjahresvergleich: Ist-Monat aus bwa_entries/daily_items vs. gespeichertes Vorjahr."""
    if not re.fullmatch(VALID_MONTH, month):
        raise HTTPException(400, "month (YYYY-MM) ist Pflicht")
    prev_month = f"{int(month[:4]) - 1}{month[4:]}"
    con_bwa = _bwa_conn()
    rep = _report_conn()
    try:
        cur = con_bwa.cursor()
        current = _merged_entries(cur, month)
        prev_rows = {r["field"]: r["amount"] for r in rep.execute(
            "SELECT field, amount FROM vv_prev WHERE month = ?", (prev_month,))}
        lines = []
        for key, label, _grp in INPUT_FIELDS:
            c = (current.get(key) or 0) / 100.0
            p = prev_rows.get(key, 0.0)
            delta = round(c - p, 2)
            pct = round(delta / p * 100, 2) if p else None
            lines.append({"key": key, "label": label, "current": round(c, 2),
                          "prev": p, "delta": delta, "pct": pct})
        return {"month": month, "prevMonth": prev_month, "lines": lines}
    finally:
        con_bwa.close()
        rep.close()


@router.get("/report/proposals")
async def report_proposals():
    """Nicht gebuchte Rechnungen als Buchungsvorschläge (Telegram/Upload/E-Mail)."""
    con = _invoice_conn()
    rep = _report_conn()
    try:
        booked = {r["invoice_id"] for r in rep.execute("SELECT invoice_id FROM bookings")}
        rows = []
        for r in con.execute("SELECT * FROM invoices ORDER BY date DESC, rowid DESC"):
            if r["email_id"] in booked:
                continue
            cat = (r["category"] or "Sonstiges").strip()
            learned = _learned_konto(rep, r["vendor"])
            if learned:
                konto, hits = learned
                suggestion = "gelernt"
            else:
                konto, hits = KATEGORIE_KONTO.get(cat, "6850"), 0
                suggestion = "kategorie"
            rows.append({
                "invoiceId": r["email_id"], "vendor": r["vendor"],
                "subject": r["subject"], "date": r["date"],
                "amountCents": r["amount_cents"], "currency": r["currency"],
                "category": cat, "source": r["source"],
                "sourceLabel": SOURCES_DE.get(r["source"], r["source"]),
                "suggestedKonto": konto,
                "suggestionSource": suggestion,
                "suggestionHits": hits,
                "hasPdf": _has_pdf(r["email_id"]),
            })
        return {"proposals": rows}
    finally:
        con.close()
        rep.close()


@router.post("/report/book")
async def report_book(request: Request):
    """Vorschlag bestätigen: SuSa-Zeile (Soll im Monat der Rechnung) anlegen,
    optional als OPOS führen. {invoiceId, month?, konto, beschriftung?,
    betrag?, opos: bool, rechnungsNr?}"""
    body = await _read_json(request)
    inv_id = str(body.get("invoiceId") or "")
    konto = str(body.get("konto") or "").strip()
    if not inv_id or not konto:
        raise HTTPException(400, "invoiceId und konto sind Pflicht")
    con_inv = _invoice_conn()
    try:
        inv = con_inv.execute("SELECT * FROM invoices WHERE email_id = ?", (inv_id,)).fetchone()
    finally:
        con_inv.close()
    if inv is None:
        raise HTTPException(404, "Rechnung nicht gefunden")
    rep = _report_conn()
    try:
        if rep.execute("SELECT 1 FROM bookings WHERE invoice_id = ?", (inv_id,)).fetchone():
            raise HTTPException(409, "Rechnung ist bereits gebucht")
        month = str(body.get("month") or (inv["date"] or "")[:7])[:7]
        if not re.fullmatch(VALID_MONTH, month):
            month = datetime.now().strftime("%Y-%m")
        betrag = float(body["betrag"]) if body.get("betrag") is not None \
            else (inv["amount_cents"] or 0) / 100.0
        cur = rep.cursor()
        blatt, beschrift = _konto_meta(konto, cur)
        beschrift = str(body.get("beschriftung") or beschrift or inv["vendor"] or "")[:120]
        with rep:
            susa_id = cur.execute(
                "INSERT INTO susa_entries (month, blatt, konto, beschriftung, soll_monat, "
                "soll_kum, saldo_sh, is_kreditor, invoice_id) VALUES (?,?,?,?,?,?,'S',?,?)",
                (month, blatt, konto, beschrift, betrag, betrag,
                 1 if (len(konto) >= 5 and konto.startswith("7")) else 0, inv_id)).lastrowid
            opos_id = None
            if body.get("opos"):
                opos_id = cur.execute(
                    "INSERT INTO opos_entries (month, konto, beschriftung, rechnungs_nr, "
                    "datum, betrag, buchungstext, invoice_id) VALUES (?,?,?,?,?,?,?,?)",
                    (month, konto, beschrift, str(body.get("rechnungsNr") or ""),
                     inv["date"] or "", betrag, inv["subject"] or "", inv_id)).lastrowid
            cur.execute("INSERT INTO bookings (invoice_id, month, konto, amount, susa_id, opos_id) "
                        "VALUES (?,?,?,?,?,?)", (inv_id, month, konto, betrag, susa_id, opos_id))
        _learn_vendor_account(rep, inv["vendor"] or beschrift, konto)
        return {"ok": True, "month": month, "konto": konto, "susaId": susa_id}
    finally:
        rep.close()


@router.delete("/report/book/{invoice_id}")
async def report_unbook(invoice_id: str):
    """Buchung stornieren: SuSa-/OPOS-Zeile löschen, Rechnung wird wieder Vorschlag."""
    rep = _report_conn()
    try:
        b = rep.execute("SELECT * FROM bookings WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if b is None:
            raise HTTPException(404, "Keine Buchung gefunden")
        with rep:
            if b["susa_id"]:
                rep.execute("DELETE FROM susa_entries WHERE id = ?", (b["susa_id"],))
            if b["opos_id"]:
                rep.execute("DELETE FROM opos_entries WHERE id = ?", (b["opos_id"],))
            rep.execute("DELETE FROM bookings WHERE invoice_id = ?", (invoice_id,))
        return {"ok": True}
    finally:
        rep.close()


from xml.sax.saxutils import escape as xesc  # noqa: E402


def _sheet_xml(rows: list[list]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for ri, row in enumerate(rows, 1):
        out.append(f'<row r="{ri}">')
        for ci, val in enumerate(row, 1):
            ref = f"{chr(64 + ci)}{ri}"
            if isinstance(val, (int, float)):
                out.append(f'<c r="{ref}"><v>{val}</v></c>')
            else:
                out.append(f'<c r="{ref}" t="inlineStr"><is><t>{xesc(str(val))}</t></is></c>')
        out.append('</row>')
    out.append('</sheetData></worksheet>')
    return ''.join(out)

def _build_xlsx(sheets: dict[str, list[list]]) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + '</Types>')
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        names = list(sheets)
        z.writestr('xl/workbook.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + ''.join(f'<sheet name="{xesc(n)[:31]}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, n in enumerate(names, 1)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(names) + 1)) + '</Relationships>')
        for i, n in enumerate(names, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', _sheet_xml(sheets[n]))
    return buf.getvalue()



@router.get("/report/export")
async def report_export(month: str = Query(...)):
    """Monatsreport als .xlsx im DATEV-Layout (KER-Blatt bleibt im BWA-Tab).
    Stdlib-only Minimal-xlsx-Writer (openpyxl ist im Backend-venv nicht vorhanden)."""
    import base64 as b64
    if not re.fullmatch(VALID_MONTH, month):
        raise HTTPException(400, "month (YYYY-MM) ist Pflicht")

    rep = _report_conn()
    try:
        susa_header = ["Konto", "Beschriftung", "EB-Wert", "EB S/H", "Soll (Monat)",
                       "Haben (Monat)", "kum. Soll", "kum. Haben", "Saldo", "Saldo S/H"]
        susa_rows = [susa_header]
        for e in _susa_response(rep, month):
            saldo = (e["eb_wert"] * (1 if e.get("eb_sh") == "S" else -1)
                     + e["soll_kum"] - e["haben_kum"])
            susa_rows.append([e["konto"] or "", e["beschriftung"],
                              round(e["eb_wert"], 2), e.get("eb_sh") or "",
                              round(e["soll_monat"], 2), round(e["haben_monat"], 2),
                              round(e["soll_kum"], 2), round(e["haben_kum"], 2),
                              round(saldo, 2), "S" if saldo >= 0 else "H"])
        opos_rows = [["Konto", "Beschriftung", "Rechnungs-Nr.", "Datum", "Fälligkeit",
                      "Betrag", "Buchungstext"]]
        for o in rep.execute("SELECT * FROM opos_entries WHERE month = ?", (month,)):
            opos_rows.append([o["konto"], o["beschriftung"], o["rechnungs_nr"], o["datum"],
                              o["faelligkeit"], round(o["betrag"], 2), o["buchungstext"]])
        data = _build_xlsx({f"SuSa {month}": susa_rows, f"OPOS {month}": opos_rows})
        return {"filename": f"Report_Scialdone_{month}.xlsx",
                "dataBase64": b64.b64encode(data).decode("ascii")}
    finally:
        rep.close()


@router.post("/invoices/upload")
async def invoice_upload(request: Request):
    """Manueller Upload: {filename, dataBase64, source? (upload|telegram|email),
    vendor?, date? (YYYY-MM-DD), amountCents?, currency?, category?}."""
    import base64 as b64
    body = await _read_json(request)
    source = body.get("source") or "upload"
    if source not in SOURCES:
        raise HTTPException(400, f"source muss einer von {SOURCES} sein")
    raw = body.get("dataBase64")
    if not isinstance(raw, str) or not raw:
        raise HTTPException(400, "dataBase64 fehlt")
    try:
        pdf_bytes = b64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(400, "dataBase64 ist kein gültiges Base64")
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "PDF zu groß (max 20 MB)")
    filename = str(body.get("filename") or "rechnung.pdf")
    vendor = str(body.get("vendor") or filename.rsplit(".", 1)[0])[:120]
    date = str(body.get("date") or "") or datetime.now().strftime("%Y-%m-%d")
    con = _invoice_conn()
    try:
        with con:
            created = _insert_invoice(
                con, source=source, filename=filename, vendor=vendor,
                subject=str(body.get("subject") or f"Rechnung {vendor}")[:200],
                date=date, amount_cents=int(body.get("amountCents") or 0),
                currency=str(body.get("currency") or "EUR"),
                category=str(body.get("category") or "Sonstiges")[:60],
                pdf_bytes=pdf_bytes,
            )
        con2 = _invoice_conn()
        try:
            r = con2.execute("SELECT * FROM invoices WHERE email_id = ?", (created["id"],)).fetchone()
            return {"ok": True, "invoice": _row_to_invoice(r)}
        finally:
            con2.close()
    finally:
        con.close()


@router.get("/bwa/export")
async def bwa_export(month: str = Query(...)):
    """BWA (KER) eines Monats als .xlsx: Erfassungswerte + berechnetes Ergebnis."""
    import base64 as b64
    if not re.fullmatch(VALID_MONTH, month):
        raise HTTPException(400, "month (YYYY-MM) ist Pflicht")
    con = _bwa_conn()
    try:
        entries = _merged_entries(con.cursor(), month)
    finally:
        con.close()
    r = compute_bwa(entries)
    rows: list[list] = [[f"BWA {month_label_de(month)}", "", ""], ["Gruppe", "Position", "Betrag EUR"]]
    for key, label, group in INPUT_FIELDS:
        rows.append([group, label, round(_v(entries, key) / 100, 2)])
    rows.append(["", "", ""])
    for key, label in (("gesamtleistung", "Gesamtleistung"), ("rohertrag", "Rohertrag"),
                       ("betrieblicherRohertrag", "Betrieblicher Rohertrag"),
                       ("gesamtkosten", "Gesamtkosten"), ("betriebsergebnis", "Betriebsergebnis"),
                       ("ergebnisVorSteuern", "Ergebnis vor Steuern"),
                       ("vorlaeufigesErgebnis", "Vorläufiges Ergebnis")):
        rows.append(["Ergebnis", label, round(r[key] / 100, 2)])
    data = _build_xlsx({f"BWA {month}": rows})
    return {"filename": f"BWA_{month}.xlsx", "dataBase64": b64.b64encode(data).decode("ascii")}
