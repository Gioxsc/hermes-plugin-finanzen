"""Buchhalter — Regel-Engine für automatische Buchungen (SKR04).

Entscheidet für jede unbebuchte Rechnung aus invoices.db:
  konto        — DATEV-Konto (SKR04)
  confidence   — 'hoch' (gelernter Lieferant) | 'regel' (Kategorie-Regel) | 'unklar'
  auto_book    — True nur bei 'hoch' oder ('regel' und AUTO_RULES an)

Bucht direkt in report.db (gleiche Logik wie /report/book im Plugin-Backend)
und lernt aus jeder Buchung: Lieferant -> Konto (Tabelle vendor_accounts).
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent   # …/finanzen
sys.path.insert(0, str(PLUGIN_DIR / "dashboard"))
import report_db  # noqa: E402

# --- Kategorie -> SKR04-Konto (Grundregeln, im Plugin-Bestätigungsdialog änderbar)
KATEGORIE_KONTO = {
    "Material": "5300",      # Wareneingang 7% Vorsteuer
    "Raum": "6310",          # Miete unbewegliche Wirtschaftsgüter
    "Versicherung": "6400",  # Versicherungen
    "Personal": "6010",      # Löhne
    "Software": "6850",      # Sonstiger Betriebsbedarf
    "Fahrzeug": "6850",
    "Werbung": "6850",
    "Sonstiges": "6850",
}

# Verbindlichkeiten (Kreditoren, Blatt 4) — wird der Rechnung zugeordnet,
# wenn der Betrag noch offen ist (opos=True).
DEFAULT_KREDITOR = "3300"  # Verbindlichkeiten aus Lieferungen+Leistungen

_VAT_HINTS = {
    "19%": {"Material": "5400"},
    "7%": {"Material": "5300"},
}

STOPWORDS = ("gmbh & co. kg", "gmbh & co kg", "gmbh", "kg", "ag", "ohg", "ug",
             "e. k.", "e.k.", "ek", "s.r.l", "srl", "s.p.a", "spa", "bv", "ltd",
             "inc", "llc", "inh.", "gbr", "stb.")


def vendor_norm(name: str) -> str:
    t = (name or "").lower().strip()
    t = re.sub(r"[^\wäöüß&.\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    for w in sorted(STOPWORDS, key=len, reverse=True):
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def decide(invoice: dict, con: sqlite3.Connection, auto_rules: bool = False) -> dict:
    """Buchungsentscheidung für eine Rechnung. invoice: dict aus invoices.db."""
    cat = (invoice.get("category") or "Sonstiges").strip()
    vendor = invoice.get("vendor") or ""
    norm = vendor_norm(vendor)

    learned = None
    if norm:
        row = con.execute("SELECT konto, hits FROM vendor_accounts WHERE vendor_norm = ?",
                          (norm,)).fetchone()
        if row is None:
            best = None
            for r in con.execute("SELECT vendor_norm, konto, hits FROM vendor_accounts"):
                common = set(norm.split()) & set(r["vendor_norm"].split())
                if common and (len(common) >= 2 or any(len(t) >= 5 for t in common)):
                    if best is None or len(common) > best[2]:
                        best = (r["konto"], r["hits"], len(common))
            if best:
                learned = best[0]
        else:
            learned = row["konto"]

    if learned:
        return {"konto": learned, "confidence": "hoch", "auto_book": True,
                "reason": f"Lieferant gelernt ({vendor})"}
    if cat in KATEGORIE_KONTO and cat != "Sonstiges":
        return {"konto": KATEGORIE_KONTO[cat], "confidence": "regel",
                "auto_book": bool(auto_rules), "reason": f"Kategorie-Regel: {cat}"}
    return {"konto": KATEGORIE_KONTO["Sonstiges"], "confidence": "unklar",
            "auto_book": False, "reason": f"Kategorie '{cat}' nicht eindeutig"}


def book_invoice(con: sqlite3.Connection, invoice: dict, konto: str,
                 opos: bool = False) -> int:
    """Bucht eine Rechnung in die SuSa (Soll im Monat des Belegs), optional OPOS.
    Liefert susa_id. Erzeugt keine bookings-Verknüpfung — das macht der Plugin-Flow;
    hier wird invoices.email_id in susa_entries.invoice_id hinterlegt, damit der
    Vorschlags-Tab die Rechnung als gebucht behandelt (bookings fehlt dort nicht:
    proposals prüfen bookings — deshalb erstellen wir den Eintrag ebenfalls)."""
    month = (invoice.get("date") or "")[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        from datetime import datetime
        month = datetime.now().strftime("%Y-%m")
    amount = (invoice.get("amount_cents") or 0) / 100.0
    beschrift = (invoice.get("vendor") or "")[:120]
    is_kred = len(konto) >= 5 and konto.startswith("7")
    if is_kred:
        blatt = 4
    else:
        first = (konto[:1] or "6")
        blatt = {"0": 1, "1": 1, "2": 1, "3": 2, "4": 2, "5": 2, "6": 3, "7": 3, "9": 3}.get(first, 3)
    inv_id = invoice.get("email_id") or ""
    cur = con.cursor()
    susa_id = cur.execute(
        "INSERT INTO susa_entries (month, blatt, konto, beschriftung, soll_monat, "
        "soll_kum, saldo_sh, is_kreditor, invoice_id) VALUES (?,?,?,?,?,'S',?,?)",
        (month, blatt, konto, beschrift, amount,
         1 if is_kred else 0, inv_id)).lastrowid
    opos_id = None
    if opos:
        opos_id = cur.execute(
            "INSERT INTO opos_entries (month, konto, beschriftung, rechnungs_nr, "
            "datum, betrag, buchungstext, invoice_id) VALUES (?,?,?,?,?,?,?,?)",
            (month, konto, beschrift, "", invoice.get("date") or "", amount,
             invoice.get("subject") or "", inv_id)).lastrowid
    if month:
        con.execute("INSERT OR IGNORE INTO bookings (invoice_id, month, konto, amount, susa_id, opos_id) "
                    "VALUES (?,?,?,?,?,?)", (inv_id, month, konto, amount, susa_id, opos_id))
    # lernen
    vnorm = vendor_norm(invoice.get("vendor") or "")
    if vnorm:
        con.execute(
            "INSERT INTO vendor_accounts (vendor_norm, vendor, konto) VALUES (?,?,?) "
            "ON CONFLICT (vendor_norm) DO UPDATE SET konto = excluded.konto, "
            "hits = hits + 1, last_used = datetime('now')",
            (vnorm, beschrift, konto))
    con.commit()
    return susa_id


def run_cycle(invoices_db: str, auto_rules: bool = False, dry_run: bool = True) -> list[dict]:
    """Ein Durchlauf: alle nicht gebuchten Rechnungen entscheiden (+ ggf. buchen)."""
    con_inv = sqlite3.connect(invoices_db)
    con_inv.row_factory = sqlite3.Row
    try:
        invoices = [dict(r) for r in con_inv.execute(
            "SELECT * FROM invoices ORDER BY date DESC, rowid DESC")]
    finally:
        con_inv.close()
    con = report_db.connect()
    try:
        booked = {r["invoice_id"] for r in con.execute("SELECT invoice_id FROM bookings")}
        results = []
        for inv in invoices:
            if inv["email_id"] in booked:
                continue
            d = decide(inv, con, auto_rules=auto_rules)
            d["invoice"] = inv
            d["booked"] = False
            if d["auto_book"] and not dry_run:
                try:
                    book_invoice(con, inv, d["konto"], opos=False)
                    d["booked"] = True
                except Exception as e:  # einzelne Buchung darf den Lauf nicht abreißen lassen
                    d["error"] = str(e)
            results.append(d)
        return results
    finally:
        con.close()


# --- Bot-Laufzeit -------------------------------------------------------------

INVOICES_DB = os.environ.get("NULLEINS_INVOICES_DB", "/Users/dwfb/nullaufeins/data/invoices.db")
AUTO_RULES = os.environ.get("BUCHHALTER_AUTO_RULES", "0") == "1"
POLL = int(os.environ.get("BUCHHALTER_POLL_SECONDS", "120"))
TELEGRAM_TOKEN = os.environ.get("PLUTOS_TELEGRAM_TOKEN", "")
ALLOWED = {int(x) for x in os.environ.get("PLUTOS_ALLOWED_CHAT_IDS", "8950251701").split(",") if x.strip()}


def load_env() -> None:
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def telegram_send(text: str) -> None:
    if not TELEGRAM_TOKEN or not ALLOWED:
        return
    import json
    import urllib.request
    for chat_id in ALLOWED:
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass


def summarize(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["🧾 Buchhalter:"]
    for d in results:
        inv = d["invoice"]
        betrag = (inv.get("amount_cents") or 0) / 100.0
        if d["booked"]:
            lines.append(f"✅ {inv.get('vendor')} · {betrag:.2f} € → Konto {d['konto']} ({d['reason']})")
        elif d["auto_book"]:
            lines.append(f"⚠️ Würde buchen: {inv.get('vendor')} · {betrag:.2f} € → Konto {d['konto']} ({d['reason']})")
        else:
            lines.append(f"📋 Vorschlag: {inv.get('vendor')} · {betrag:.2f} € → Konto {d['konto']} ({d['reason']}) — bitte im Plugin bestätigen")
    return "\n".join(lines)


def main() -> None:
    load_env()
    global AUTO_RULES, TELEGRAM_TOKEN, ALLOWED
    AUTO_RULES = os.environ.get("BUCHHALTER_AUTO_RULES", "0") == "1"
    TELEGRAM_TOKEN = os.environ.get("PLUTOS_TELEGRAM_TOKEN", "")
    ALLOWED = {int(x) for x in os.environ.get("PLUTOS_ALLOWED_CHAT_IDS", "8950251701").split(",") if x.strip()}
    print(f"[buchhalter] gestartet (auto_rules={AUTO_RULES}, poll={POLL}s)", flush=True)
    seen: set[str] = set()
    first = True
    while True:
        try:
            # auto_rules=True: auch Kategorie-Regeln buchen automatisch.
            # auto_rules=False: nur gelernte Lieferanten (Konfidenz 'hoch') buchen automatisch.
            results = run_cycle(INVOICES_DB, auto_rules=AUTO_RULES, dry_run=False)
            open_ids = {d["invoice"]["email_id"] for d in results}
            new_results = [d for d in results if d["invoice"]["email_id"] not in seen]
            seen = open_ids
            # Beim ersten Lauf alles melden (Stand übernehmen), danach nur Neues.
            msg = summarize(results if first else new_results)
            first = False
            if msg:
                telegram_send(msg)
                print(msg, flush=True)
        except Exception as e:
            print(f"[buchhalter] Fehler im Durchlauf: {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
