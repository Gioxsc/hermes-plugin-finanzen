# hermes-plugin-finanzen

Buchhaltungs-Dashboard für **Hermes Desktop** – läuft auf **Windows und macOS**.

Tabs: **Tagebuch** (tägliche Einnahmen/Ausgaben mit Bon) · **BWA** (DATEV-KER, Live-Ergebnis,
Kostenarten-Donut, Excel-Export, Drucken) · **Rechnungen** (Upload, Vorschau, Zahlungszuordnung) ·
**Vorschläge** (Rechnung → Konto buchen, lernt Lieferant→Konto) · **SuSa** · **OPOS** ·
**Vorjahresvergleich**. Alle Monate/Jahre frei wählbar (Monat + Jahr, ◀ ▶, Heute).

Kein nulleins-Server nötig: Datenbanken werden beim ersten Aufruf automatisch angelegt.

## Aufbau

```
finanzen/
├── plugin.yaml / __init__.py      # Agent-Hälfte (keine Tools)
├── dashboard/
│   ├── manifest.json              # { "name": "finanzen", "api": "plugin_api.py" }
│   ├── plugin_api.py              # Backend → /api/plugins/finanzen/
│   └── report_db.py               # SuSa / OPOS / Buchungen (report.db)
└── desktop/plugin.js              # Oberfläche (wird von Hermes nach desktop-plugins/ kopiert)
```

## Installation

Der Plugin-Ordner gehört in `<HERMES_HOME>/plugins/finanzen`:

| System  | HERMES_HOME (Standard)                         |
|---------|------------------------------------------------|
| Windows | `%LOCALAPPDATA%\hermes` (`C:\Users\<Name>\AppData\Local\hermes`) |
| macOS   | `~/.hermes`                                    |

Am einfachsten über Hermes selbst (beide Systeme):

```bash
hermes plugins install Gioxsc/hermes-plugin-finanzen
hermes plugins enable finanzen
```

Oder manuell:

```powershell
# Windows (PowerShell)
git clone https://github.com/Gioxsc/hermes-plugin-finanzen.git "$env:LOCALAPPDATA\hermes\plugins\finanzen"
hermes plugins enable finanzen
```

```bash
# macOS
git clone https://github.com/Gioxsc/hermes-plugin-finanzen.git ~/.hermes/plugins/finanzen
hermes plugins enable finanzen
```

Danach **Hermes Desktop komplett neu starten** (das Backend wird nur beim Start geladen) und in der
Seitenleiste **Finanzen** öffnen. Falls die Seite nicht erscheint: Einstellungen → Plugins →
„finanzen“ einschalten bzw. ⌘K / Strg+K → *Reload desktop plugins*.

> `hermes plugins enable finanzen` ist Pflicht: Ohne Eintrag in `plugins.enabled` (config.yaml)
> lädt Hermes das Python-Backend aus Sicherheitsgründen nicht – die Seite zeigt dann
> „Backend nicht erreichbar“.

## Daten

Standardordner `<Home>/nullaufeins/data/` (`bwa.db`, `invoices.db`, `invoice-files/`,
`daily-receipts/`), SuSa/OPOS in `dashboard/data/report.db`. Abweichende Pfade per Umgebungsvariable:
`NULLEINS_HOME`, `NULLEINS_BWA_DB`, `NULLEINS_INVOICES_DB`, `NULLEINS_INVOICE_FILES`,
`NULLEINS_DAILY_RECEIPTS`.

Daten zwischen Mac und Windows übertragen: diese Dateien kopieren (Hermes vorher beenden):
`nullaufeins/data/*` und `<HERMES_HOME>/plugins/finanzen/dashboard/data/report.db`.
Die `.db`-Dateien sind per `.gitignore` vom Repository ausgeschlossen.

## Hilfsskripte

Windows: `python`, macOS: `python3`.

- `python monatsabschluss.py 2026-09` – Monatsabschluss-Notiz (Vault `~/Documents/nullaufeins`)
- `python dashboard/import_xlsx.py <DATEV.xlsx>` – Excel-Import (benötigt `pip install openpyxl`)
- `python plutos/plutos_bot.py`, `python buchhalter/buchhalter_bot.py` – Telegram-Bots
  (Token in `<HERMES_HOME>/.env`: `PLUTOS_TELEGRAM_TOKEN`)
- `python test_standalone.py` – Backend-Selbsttest in leerer Temp-Umgebung
