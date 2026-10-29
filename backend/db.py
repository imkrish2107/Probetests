"""SQLite schema + helpers (full backend.md schema; init is idempotent)."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  wa_phone_number_id TEXT UNIQUE, wa_display_number TEXT,
  timezone TEXT DEFAULT 'Asia/Kolkata', hours TEXT DEFAULT '{}',
  slot_minutes INTEGER DEFAULT 30, seats_per_slot INTEGER DEFAULT 10,
  menu TEXT DEFAULT '[]', prices TEXT DEFAULT '', faqs TEXT DEFAULT '[]',
  languages TEXT DEFAULT '["English"]',
  owner_whatsapp TEXT DEFAULT '', crm_webhook_url TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner', created_at TEXT DEFAULT (datetime('now')),
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  wa_user_id TEXT NOT NULL, phone TEXT DEFAULT '', name TEXT DEFAULT '',
  language TEXT DEFAULT '', stage TEXT DEFAULT 'new',
  tags TEXT DEFAULT '[]', notes TEXT DEFAULT '',
  first_call_at TEXT, last_call_at TEXT, last_inbound_at TEXT, auto_reply_at TEXT,
  calls_count INTEGER DEFAULT 0, call_permission INTEGER DEFAULT 0,
  UNIQUE (business_id, wa_user_id)
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  contact_id INTEGER REFERENCES contacts(id), wa_call_id TEXT UNIQUE,
  direction TEXT DEFAULT 'inbound', source TEXT,
  language TEXT DEFAULT '', started_at TEXT, ended_at TEXT, duration_s INTEGER DEFAULT 0,
  outcome TEXT DEFAULT 'answered', summary TEXT DEFAULT '', crm_changes TEXT DEFAULT '{}',
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
  audio_seconds REAL DEFAULT 0, cost_usd REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transcripts (
  id INTEGER PRIMARY KEY, call_id INTEGER NOT NULL REFERENCES calls(id),
  role TEXT NOT NULL, text TEXT NOT NULL, language TEXT DEFAULT '', at TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  contact_id INTEGER REFERENCES contacts(id), call_id INTEGER REFERENCES calls(id),
  name TEXT DEFAULT '', party_size INTEGER DEFAULT 2, slot TEXT NOT NULL, note TEXT DEFAULT '',
  status TEXT DEFAULT 'booked', reminder_sent_at TEXT,
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  contact_id INTEGER REFERENCES contacts(id), call_id INTEGER REFERENCES calls(id),
  type TEXT NOT NULL, details TEXT DEFAULT '', urgency TEXT DEFAULT 'normal',
  status TEXT DEFAULT 'open', done_note TEXT DEFAULT '', done_by INTEGER REFERENCES users(id),
  created_at TEXT DEFAULT (datetime('now')), done_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  contact_id INTEGER REFERENCES contacts(id), call_id INTEGER REFERENCES calls(id),
  booking_id INTEGER REFERENCES bookings(id), task_id INTEGER REFERENCES tasks(id),
  kind TEXT NOT NULL, template TEXT DEFAULT '', language TEXT DEFAULT '',
  body TEXT DEFAULT '', wa_message_id TEXT, status TEXT DEFAULT 'queued',
  error TEXT DEFAULT '', sent_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
