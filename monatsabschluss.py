#!/usr/bin/env python3
"""Monatsabschluss: erzeugt aus bwa.db + report.db eine Quellen-Notiz im Obsidian Vault.

Nutzung:
    python3 monatsabschluss.py 2026-09            # konkreter Monat (Windows: python statt python3)
    python3 monatsabschluss.py                    # letzter vollständiger Monat
    python3 monatsabschluss.py --no-gate                             # Notiz schreiben, Vault-Gate überspringen

Ablauf nach Erzeugung (vom Bot auszuführen):
    cd ~/Documents/nullaufeins
    python3 scripts/wiki_tool.py source-stamp
    python3 scripts/wiki_tool.py build && python3 scripts/wiki_tool.py lint && python3 scripts/wiki_tool.py source-lint
    (dann Wiki-Note kompilieren und erneut build + lint)
"""
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

_NULLEINS = Path(os.environ.get("NULLEINS_HOME", Path.home() / "nullaufeins"))
BWA_DB = Path(os.environ.get("NULLEINS_BWA_DB", _NULLEINS / "data" / "bwa.db"))
REPORT_DB = Path(__file__).resolve().parent / "dashboard" / "data" / "report.db"
VAULT = Path.home() / "Documents/nullaufeins"
SOURCES = VAULT / "Raw/Sources"

FELDE_LABELLE = {
    "umsatz": "Umsatz",
    "personal": "Personal",
    "raum": "Raum",
    "werbungReise": "Werbung/Reise",
    "versicherungen": "Versicherungen",
    "sonstigeKosten": "Sonstige Kosten",
}

def eur(cents: int) -> str:
    return f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"

def last_closed_month() -> str:
    today = date.today()
    first_this = today.replace(day=1)
    prev = (first_this - __import__("datetime").timedelta(days=1))
    return prev.strftime("%Y-%m")

def fmt_markdown(month: str, bwa: dict, opos: dict, susa_count: int) -> str:
    umsatz = bwa.get("umsatz", 0)
    kosten = sum(v for k, v in bwa.items() if k != "umsatz")
    ergebnis = umsatz - kosten
    lines = [
        f"# BWA Monatsabschluss {month}",
        "",
        f"Automatisch erzeugt am {date.today().isoformat()} aus `data/bwa.db` (bwa_entries) "
        f"und `<Plugin>/dashboard/data/report.db` (opos_entries, susa_entries) "
        f"des Finanzen-Plugins. Alle Beträge in EUR (Cent-basiert, gerundet auf 2 Nachkommastellen).",
        "",
        "## BWA-Zahlen",
        "",
        "| Feld | Betrag |",
        "|---|---|",
    ]
    for key in ["umsatz", "personal", "raum", "werbungReise", "versicherungen", "sonstigeKosten"]:
        if key in bwa:
            lines.append(f"| {FELDE_LABELLE.get(key, key)} | {eur(bwa[key])} |")
    lines += [
        f"| **Summe Kosten** | **{eur(kosten)}** |",
        f"| **Ergebnis** | **{eur(ergebnis)}** |",
        "",
        "## Offene Posten (Monatsende)",
        "",
    ]
    if opos["count"]:
        lines += [
            f"- Anzahl offene Posten: {opos['count']}",
            f"- Summe offene Posten: {eur(opos['sum'])}",
            f"- Überfällig: {opos['ueberfaellig']} von {opos['count']}",
        ]
    else:
        lines.append("- Keine offenen Posten zum Monatsende.")
    lines += [
        "",
        f"SuSa-Positionen im Monat: {susa_count}",
        "",
        "## Status",
        "",
        "Monat abgeschlossen gebucht. Diese Quelle ist der Stand zum Abschlusszeitpunkt; "
        "spätere Korrekturen ändern diese Notiz nicht (Quellen bleiben originalgetreu).",
        "",
    ]
    return "\n".join(lines)

def main() -> None:
    args = [a for a in sys.argv[1:]]
    skip_gate = "--no-gate" in args
    month = next((a for a in args if not a.startswith("--")), last_closed_month())

    if not BWA_DB.exists():
        sys.exit(f"Fehler: {BWA_DB} nicht gefunden")
    con = sqlite3.connect(BWA_DB)
    rows = con.execute(
        "SELECT field, amount_cents FROM bwa_entries WHERE month = ?", (month,)
    ).fetchall()
    con.close()
    if not rows:
        sys.exit(f"Fehler: keine BWA-Einträge für {month}")

    bwa = {field: cents for field, cents in rows}
    opos = {"count": 0, "sum": 0, "ueberfaellig": 0}
    susa_count = 0
    if REPORT_DB.exists():
        rcon = sqlite3.connect(REPORT_DB)
        opos["count"], opos["sum"] = rcon.execute(
            "SELECT COUNT(*), COALESCE(SUM(betrag), 0) FROM opos_entries WHERE month = ?",
            (month,),
        ).fetchone()
        opos["ueberfaellig"] = rcon.execute(
            "SELECT COUNT(*) FROM opos_entries WHERE month = ? AND faelligkeit < date('now')",
            (month,),
        ).fetchone()[0]
        susa_count = rcon.execute(
            "SELECT COUNT(*) FROM susa_entries WHERE month = ?", (month,)
        ).fetchone()[0]
        rcon.close()

    md = fmt_markdown(month, bwa, opos, susa_count)
    SOURCES.mkdir(parents=True, exist_ok=True)
    target = SOURCES / f"bwa-monatsabschluss-{month}.md"
    if target.exists():
        sys.exit(f"Fehler: {target.name} existiert bereits (Monat schon abgeschlossen)")
    body = [
        "---",
        f'Title: "BWA Monatsabschluss {month}"',
        'Author: "Finanzen-Plugin (monatsabschluss.py)"',
        f'Reference: "nullaufeins data/bwa.db + finanzen report.db, Monat {month}"',
        "ContentType:",
        '  - "markdown"',
        f"Created: {date.today().isoformat()}",
        "Processed: false",
        'sha256: ""          # via `python3 scripts/wiki_tool.py source-stamp` setzen',
        "tags:",
        '  - "source"',
        '  - "finanzen"',
        "---",
        "",
        md,
    ]
    target.write_text("\n".join(body), encoding="utf-8")
    print(f"Quelle geschrieben: {target}")

    if skip_gate:
        return
    for cmd in (
        [sys.executable, "scripts/wiki_tool.py", "source-stamp"],
        [sys.executable, "scripts/wiki_tool.py", "build"],
        [sys.executable, "scripts/wiki_tool.py", "lint"],
        [sys.executable, "scripts/wiki_tool.py", "source-lint"],
    ):
        res = subprocess.run(cmd, cwd=VAULT, capture_output=True, text=True)
        print(f"$ {' '.join(cmd[2:])}\n{(res.stdout + res.stderr).strip() or 'ok'}")
        if res.returncode != 0:
            sys.exit(f"Gate fehlgeschlagen: {' '.join(cmd)}")
    print("Vault-Gate grün. Nächster Schritt: kompilierte Wiki-Note aus dieser Quelle erstellen.")

if __name__ == "__main__":
    main()
