#!/usr/bin/env python3
"""Plutos — Telegram-Rechnungsbot für nulleins.

Fängt PDFs/Dokumente ab, die im Telegram-Chat mit dem Plutos-Bot geteilt
werden, und verbucht sie als Quelle "telegram" in der nulleins
invoices.db (data/invoice-files/). Antworten im Chat mit Bestätigung.
Duplikate (gleicher SHA-256) werden erkannt und nicht doppelt verbucht.

Konfiguration über Umgebungsvariablen (oder ~/.hermes/.env):
  PLUTOS_TELEGRAM_TOKEN   Bot-Token vom BotFather (Pflicht)
  PLUTOS_ALLOWED_CHAT_IDS erlaubte Telegram-Chat-IDs, Komma-getrennt
                          (Default: 8950251701)
  NULLEINS_INVOICES_DB    Default: /Users/dwfb/nullaufeins/data/invoices.db
  NULLEINS_INVOICE_FILES  Default: /Users/dwfb/nullaufeins/data/invoice-files
  PLUTOS_POLL_SECONDS     Poll-Intervall (Default 3)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HOME = Path.home()
ENV_FILE = HOME / ".hermes" / ".env"


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


load_env()

TOKEN = os.environ.get("PLUTOS_TELEGRAM_TOKEN", "")
ALLOWED = {int(x) for x in os.environ.get("PLUTOS_ALLOWED_CHAT_IDS", "8950251701").split(",") if x.strip()}
_HOME = Path(os.environ.get("NULLEINS_HOME", Path.home() / "nullaufeins"))
INVOICES_DB = Path(os.environ.get("NULLEINS_INVOICES_DB", _HOME / "data" / "invoices.db"))
FILES_DIR = Path(os.environ.get("NULLEINS_INVOICE_FILES", _HOME / "data" / "invoice-files"))
BWA_DB = Path(os.environ.get("NULLEINS_BWA_DB", _HOME / "data" / "bwa.db"))
DAILY_RECEIPTS_DIR = Path(os.environ.get("NULLEINS_DAILY_RECEIPTS", _HOME / "data" / "daily-receipts"))
DAILY_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic"}
POLL = int(os.environ.get("PLUTOS_POLL_SECONDS", "3"))

API = f"https://api.telegram.org/bot{TOKEN}"

# Lokale Beleg-Erkennung über den Hermes-Proxy (Nous Portal, OAuth — kein externer Key).
PROXY_URL = os.environ.get("PLUTOS_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
PROXY_MODEL = os.environ.get("PLUTOS_MODEL", "stealth/union-alpha")

EXTRACT_PROMPT = (
    "Du bist eine Buchhaltungs-Extraktion. Analysiere den Beleg und antworte "
    "AUSSCHLIESSLICH mit JSON, keine weiteren Worte: "
    '{"vendor": "Lieferant/Name", "subject": "kurzer Belegtext", "date": "JJJJ-MM-TT oder leer", '
    '"amount_euros": Zahl oder null, "category": "eine von: Software, Raum, Fahrzeug, Werbung, Personal, Material, Versicherung, Sonstiges"}. '
    "amount_euros ist IMMER der Bruttogesamtbetrag (Summe inkl. Steuern), der auf dem Beleg steht — "
    "auch bei Fremdwährung wie USD die Zahl einfach übernehmen. Schau besonders auf Zeilen wie "
    '"Total", "Total due", "Amount due", "Gesamt", "Summe". Nur bei wirklich fehlendem Betrag null. '
    "Betrag nur die Zahl, Punkt als Dezimaltrennzeichen."
)


def extract_metadata(data: bytes, mime: str) -> dict | None:
    """Belegdaten lokal über den Hermes-Proxy extrahieren. None bei Fehler."""
    import base64 as b64
    body = {
        "model": PROXY_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64.b64encode(data).decode()}"}},
                {"type": "text", "text": EXTRACT_PROMPT},
            ],
        }],
        "max_tokens": 300,
        "temperature": 0.1,
    }
    return _chat(body)


def extract_metadata_pdf(data: bytes) -> dict | None:
    """PDFs: Text mit pypdf ziehen, dann Text-Analyse über den Proxy."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:4])
    except Exception as exc:  # noqa: BLE001
        log(f"PDF-Textextraktion fehlgeschlagen: {exc}")
        return None
    text = text.strip()
    if not text:
        log("PDF ohne Textebene (Scan) — keine Extraktion möglich.")
        return None
    body = {
        "model": PROXY_MODEL,
        "messages": [{
            "role": "user",
            "content": f"Belegtext:\n\n{text[:8000]}\n\n{EXTRACT_PROMPT}",
        }],
        "max_tokens": 300,
        "temperature": 0.1,
    }
    return _chat(body)


def _chat(body: dict) -> dict | None:
    req = urllib.request.Request(PROXY_URL, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "authorization": "Bearer plutos-local"})
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            out = json.loads(res.read())
        text = out["choices"][0]["message"]["content"].strip()
        text = text[text.index("{"): text.rindex("}") + 1]
        meta = json.loads(text)
        log(f"Extraktion ({PROXY_MODEL}): {meta}")
        return meta
    except Exception as exc:  # noqa: BLE001
        log(f"Extraktion fehlgeschlagen: {exc}")
        return None


CATEGORY_MAP = {"software": "Software", "raum": "Raum", "fahrzeug": "Fahrzeug", "werbung": "Werbung",
                "marketing": "Werbung", "personal": "Personal", "material": "Material",
                "versicherung": "Versicherung", "miete": "Raum"}


def _clean_category(raw) -> str:
    low = str(raw or "").strip().lower()
    for key, val in CATEGORY_MAP.items():
        if key in low:
            return val
    return "Sonstiges"


def log(msg: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def tg(method: str, **params) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{API}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def tg_download(file_id: str) -> bytes:
    info = tg("getFile", file_id=file_id)
    path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
    with urllib.request.urlopen(url, timeout=60) as res:
        return res.read()


def ensure_source_column(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(invoices)")}
    if "source" not in cols:
        con.execute("ALTER TABLE invoices ADD COLUMN source TEXT NOT NULL DEFAULT 'email'")
        con.commit()


def sha256_of_dir_file(name: str) -> str:
    try:
        return hashlib.sha256((FILES_DIR / name).read_bytes()).hexdigest()
    except OSError:
        return ""


def existing_hashes() -> set[str]:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    return {h for h in (sha256_of_dir_file(f.name) for f in FILES_DIR.iterdir()) if h}


def book_daily_expense(date: str, label: str, amount_cents: int, data: bytes | None = None, ext: str = ".pdf") -> int:
    """Beleg zusätzlich als Tagesausgabe ins Tagebuch (daily_items) buchen.
    Return: Buchungs-ID."""
    ext = ext if ext in DAILY_EXTS else ".jpg"
    DAILY_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(BWA_DB))
    con.row_factory = sqlite3.Row
    try:
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
        with con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO daily_items (date, kind, label, amount_cents) VALUES (?, 'expense', ?, ?)",
                (date, label[:120], amount_cents),
            )
            item_id = cur.lastrowid
            if data:
                receipt = f"{item_id}{ext}"
                (DAILY_RECEIPTS_DIR / receipt).write_bytes(data)
                cur.execute("UPDATE daily_items SET receipt_file = ? WHERE id = ?", (receipt, item_id))
        return item_id
    finally:
        con.close()


def book_invoice(data: bytes, suggested_vendor: str, caption: str, ext: str = ".pdf", meta: dict | None = None) -> tuple[bool, str, str]:
    """Verbucht den Beleg. Return (neu_verbucht?, Meldung, Rechnungs-ID)."""
    digest = hashlib.sha256(data).hexdigest()
    if digest in existing_hashes():
        return False, "Diese Datei ist schon verbucht (Duplikat).", ""

    meta = meta or {}
    vendor = (meta.get("vendor") or caption.strip() or suggested_vendor or "Unbekannt")[:120]
    subject = (caption.strip() or meta.get("subject") or f"Rechnung {vendor}")[:200]
    date = meta.get("date") if re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta.get("date") or "")) else None
    date = date or datetime.now().strftime("%Y-%m-%d")
    try:
        amount_cents = int(round(float(meta["amount_euros"]) * 100)) if meta.get("amount_euros") is not None else 0
    except (TypeError, ValueError):
        amount_cents = 0
    category = _clean_category(meta.get("category")) if meta else "Sonstiges"

    inv_id = uuid.uuid4().hex
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    (FILES_DIR / f"{inv_id}{ext}").write_bytes(data)

    con = sqlite3.connect(str(INVOICES_DB))
    con.row_factory = sqlite3.Row
    try:
        ensure_source_column(con)
        with con:
            con.execute(
                "INSERT INTO invoice_files (email_id, filename) VALUES (?, ?)",
                (inv_id, f"{inv_id}{ext}"),
            )
            con.execute(
                "INSERT INTO invoices (email_id, vendor, subject, date, amount_cents, currency, category, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'telegram')",
                (inv_id, vendor, subject, date, amount_cents, "EUR", category),
            )
    finally:
        con.close()
    # Zusätzlich als Tagesausgabe ins Tagebuch buchen (mit Bon als Anhang).
    daily_note = ""
    if amount_cents > 0:
        try:
            book_daily_expense(date, f"{vendor} · {subject}"[:120], amount_cents, data, ext)
            daily_note = " · Auch im Tagebuch verbucht"
        except Exception as exc:  # noqa: BLE001
            log(f"Tagebuch-Buchung fehlgeschlagen: {exc}")
            daily_note = " · (Tagebuch-Buchung fehlgeschlagen)"
    return True, vendor + daily_note, inv_id


def handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return
    chat_id = msg.get("chat", {}).get("id")
    if chat_id not in ALLOWED:
        log(f"ignoriere Chat {chat_id} (nicht erlaubt)")
        return

    doc = msg.get("document")
    photo = msg.get("photo")
    if not doc and not photo:
        if msg.get("text", "").startswith("/start"):
            tg("sendMessage", chat_id=chat_id, text="Plutos hört zu. Schick mir Rechnungs-PDFs oder Fotos, ich verbuche sie als Telegram-Belege. Schnelle Ausgabe: „4,50 Bäckerei“ als Text schicken.")
            return
        # Schnelle Tagesausgabe per Text: "<Betrag> <Bezeichnung>" oder "<Bezeichnung> <Betrag>"
        text = (msg.get("text") or "").strip()
        m = re.match(r"^(\d+(?:[.,]\d{1,2})?)\s+(.+)$", text) or re.match(r"^(.+?)\s+(\d+(?:[.,]\d{1,2})?)$", text)
        if m:
            first, second = m.group(1), m.group(2)
            amount_raw, label = (first, second) if re.match(r"^\d", first) else (second, first)
            try:
                cents = int(round(float(amount_raw.replace(",", ".")) * 100))
            except ValueError:
                return
            label = label.strip()
            if cents > 0 and label:
                date = datetime.now().strftime("%Y-%m-%d")
                book_daily_expense(date, label, cents)
                log(f"Text-Ausgabe verbucht: {label} ({cents}c)")
                tg("sendMessage", chat_id=chat_id, text=f"✓ Ausgabe verbucht: {label} · {cents/100:.2f} €\n(Tagebuch {date})")
        return

    if photo:
        # Höchste verfügbare Auflösung (letztes Element = größte Größe)
        doc = {"file_id": photo[-1]["file_id"], "file_name": f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
               "file_size": photo[-1].get("file_size", 0), "mime_type": "image/jpeg"}
    name = doc.get("file_name", "rechnung.pdf")
    mime = doc.get("mime_type", "")
    is_pdf = name.lower().endswith(".pdf") or mime == "application/pdf"
    is_image = name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) or mime.startswith("image/")
    if not is_pdf and not is_image:
        tg("sendMessage", chat_id=chat_id, text=f"⚠️ {name} ist kein PDF oder Foto — ich verbuche nur PDFs und Bilder.")
        return
    if doc.get("file_size", 0) > 20 * 1024 * 1024:
        tg("sendMessage", chat_id=chat_id, text=f"⚠️ {name} ist größer als 20 MB.")
        return

    try:
        data = tg_download(doc["file_id"])
        ext = ".pdf" if is_pdf else ".jpg" if name.lower().endswith((".jpg", ".jpeg")) else ("." + name.rsplit(".", 1)[-1].lower() if "." in name else ".jpg")
        # Beleg-Erkennung: Bilder direkt, PDFs über Textebene — alles lokal über den Hermes-Proxy
        meta = None
        if is_image:
            meta = extract_metadata(data, mime or "image/jpeg")
        elif is_pdf:
            meta = extract_metadata_pdf(data)
        ok, info, _ = book_invoice(data, suggested_vendor=name.rsplit(".", 1)[0].replace("_", " "),
                                   caption=msg.get("caption", ""), ext=ext, meta=meta)
        if ok:
            amount = meta.get("amount_euros") if meta else None
            extra = f" · {amount} €" if amount is not None else ""
            log(f"verbucht: {name} ({len(data)} Bytes) -> {info}{extra}")
            tg("sendMessage", chat_id=chat_id, text=f"✓ Verbucht: {info}{extra}\n{name}\n(Eckdaten prüfen/ändern: Finanzen-Tab → Rechnungen)")
        else:
            tg("sendMessage", chat_id=chat_id, text=f"ℹ️ {name}: {info}")
    except Exception as exc:  # noqa: BLE001
        log(f"Fehler bei {name}: {exc}")
        tg("sendMessage", chat_id=chat_id, text=f"⚠️ {name} konnte nicht verbucht werden: {exc}")


def main() -> None:
    if not TOKEN:
        print("PLUTOS_TELEGRAM_TOKEN fehlt (in ~/.hermes/.env setzen).", flush=True)
        sys.exit(1)
    if not INVOICES_DB.exists():
        print(f"Invoices-DB fehlt: {INVOICES_DB}", flush=True)
        sys.exit(1)
    me = tg("getMe")["result"]
    log(f"Plutos läuft als @{me['username']} — erlaubte Chats: {sorted(ALLOWED)}")
    tg("sendMessage", chat_id=min(ALLOWED), text="🟢 Plutos ist online. Rechnungs-PDFs einfach hier teilen.")

    offset = 0
    while True:
        try:
            res = tg("getUpdates", offset=offset, timeout=25, allowed_updates=json.dumps(["message", "channel_post"]))
            for update in res.get("result", []):
                offset = update["update_id"] + 1
                handle_update(update)
        except Exception as exc:  # noqa: BLE001
            log(f"poll error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
