# Finanzen Plugin — Windows-Setup

Das Plugin läuft auf Windows und macOS. Alle Pfade sind plattformunabhängig
(`%USERPROFILE%\nullaufeins` bzw. `~/nullaufeins`).

## Voraussetzungen

1. **Python 3.10+** (`winget install Python.Python.3.12`) — `fastapi`, `uvicorn` (Hermes-Backend liefert die), für `import_xlsx.py` zusätzlich `pip install openpyxl`
2. **nulleins-Codebase** unter `C:\Users\<Name>\nullaufeins` mit den Datenbanken:
   - `data\bwa.db`
   - `data\invoices.db` + `data\invoice-files\`
   - `data\daily-receipts\`
3. **Hermes Desktop** installiert

## Installation

```powershell
git clone https://github.com/Gioxsc/hermes-plugin-finanzen.git $env:USERPROFILE\.hermes\plugins\finanzen
```

Dann Hermes Desktop neu starten (Backend lädt Plugins nur beim Start).

## Pfade anpassen (optional)

Defaults richten sich nach `NULLEINS_HOME` (Standard: Home-Verzeichnis + `nullaufeins`).
Abweichende Pfade per Umgebungsvariable:

```powershell
setx NULLEINS_HOME "D:\nulleins"
setx NULLEINS_BWA_DB "D:\nulleins\data\bwa.db"
setx NULLEINS_INVOICES_DB "D:\nulleins\data\invoices.db"
setx NULLEINS_INVOICE_FILES "D:\nulleins\data\invoice-files"
setx NULLEINS_DAILY_RECEIPTS "D:\nulleins\data\daily-receipts"
```

## Daten übertragen (Mac → Windows)

Die Daten liegen nicht im Repo (`.db` ist ausgeschlossen). Kopieren per
USB-Stick / Netzlaufwerk / `scp`:

```
~/nullaufeins/data/bwa.db
~/nullaufeins/data/invoices.db
~/nullaufeins/data/invoice-files/
~/nullaufeins/data/daily-receipts/
~/.hermes/plugins/finanzen/dashboard/data/report.db
```

Ziel unter Windows: `C:\Users\<Name>\nullaufeins\data\...` bzw.
`C:\Users\<Name>\.hermes\plugins\finanzen\dashboard\data\report.db`.
**Wichtig: Hermes Desktop vorher beenden** (sonst SQLite-Sperren).

## Hilfsskripte

- `python monatsabschluss.py 2026-09` — Monatsabschluss-Notiz (Vault-Pfad: `Documents\nullaufeins`)
- `python dashboard\import_xlsx.py <Pfad-zur-DATEV.xlsx>` — Excel-Import
- `plutos\plutos_bot.py` / `buchhalter\buchhalter_bot.py` — Telegram-Bots, laufen mit `python` statt `python3`
