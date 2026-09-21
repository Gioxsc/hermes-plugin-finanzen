"""report.db — SuSa, OPOS und Vorjahres-Vergleichswerte des Finanzen-Plugins.

Eigenstaendige DB (fasst bwa.db / invoices.db nicht an). Ein Konto pro Zeile,
Klassensummen werden beim Laden berechnet, nicht gespeichert.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "report.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS susa_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL,
  blatt INTEGER NOT NULL,
  konto TEXT NOT NULL,
  beschriftung TEXT NOT NULL DEFAULT '',
  eb_wert REAL NOT NULL DEFAULT 0,
  eb_sh TEXT NOT NULL DEFAULT 'S',
  soll_monat REAL NOT NULL DEFAULT 0,
  haben_monat REAL NOT NULL DEFAULT 0,
  soll_kum REAL NOT NULL DEFAULT 0,
  haben_kum REAL NOT NULL DEFAULT 0,
  saldo_sh TEXT NOT NULL DEFAULT 'S',
  is_kreditor INTEGER NOT NULL DEFAULT 0,
  invoice_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_susa_month ON susa_entries (month);
CREATE TABLE IF NOT EXISTS opos_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL,
  konto TEXT NOT NULL DEFAULT '',
  beschriftung TEXT NOT NULL DEFAULT '',
  rechnungs_nr TEXT NOT NULL DEFAULT '',
  datum TEXT NOT NULL DEFAULT '',
  faelligkeit TEXT NOT NULL DEFAULT '',
  betrag REAL NOT NULL DEFAULT 0,
  buchungstext TEXT NOT NULL DEFAULT '',
  invoice_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_opos_month ON opos_entries (month);
-- Vorjahr-Spalte des Vorjahresvergleichs (Monat 'YYYY-MM' = Vorjahr-Monat).
CREATE TABLE IF NOT EXISTS vv_prev (
  month TEXT NOT NULL,
  field TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (month, field)
);
-- Bestätigte Rechnungs-Buchungen: verhindert Doppelbuchungen.
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id TEXT NOT NULL UNIQUE,
  month TEXT NOT NULL,
  konto TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  susa_id INTEGER,
  opos_id INTEGER,
  confirmed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Gelernte Lieferant->Konto-Zuordnung aus bestätigten Buchungen.
CREATE TABLE IF NOT EXISTS vendor_accounts (
  vendor_norm TEXT PRIMARY KEY,
  vendor TEXT NOT NULL,
  konto TEXT NOT NULL,
  hits INTEGER NOT NULL DEFAULT 1,
  last_used TEXT NOT NULL DEFAULT (datetime('now'))
);

"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
