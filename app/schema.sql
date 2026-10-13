-- RFID Smart Automobile Parking Lots Tracking System: database schema (SQLite)
-- Nine entities from Figure 4.3 plus an audit_log table (needed for FR11).

CREATE TABLE IF NOT EXISTS owner (
  owner_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name  TEXT NOT NULL,
  category   TEXT NOT NULL CHECK (category IN ('STAFF','STUDENT','CONTRACTOR','OTHER')),
  phone      TEXT,
  department TEXT
);

CREATE TABLE IF NOT EXISTS vehicle (
  vehicle_id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id   INTEGER NOT NULL REFERENCES owner(owner_id),
  plate      TEXT NOT NULL UNIQUE,
  make_model TEXT,
  colour     TEXT,
  status     TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','BLACKLISTED'))
);

-- Only a keyed hash (HMAC-SHA256) of the tag UID is stored, never the UID itself.
CREATE TABLE IF NOT EXISTS rfid_tag (
  tag_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL REFERENCES vehicle(vehicle_id),
  uid_hash   TEXT NOT NULL UNIQUE,
  issued_at  TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  state      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (state IN ('ACTIVE','SUSPENDED','REVOKED'))
);

CREATE TABLE IF NOT EXISTS parking_lot (
  lot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  capacity      INTEGER NOT NULL CHECK (capacity > 0),
  current_count INTEGER NOT NULL DEFAULT 0 CHECK (current_count >= 0)
);

CREATE TABLE IF NOT EXISTS gate (
  gate_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name    TEXT NOT NULL UNIQUE,
  lot_id  INTEGER NOT NULL REFERENCES parking_lot(lot_id)
);

CREATE TABLE IF NOT EXISTS access_event (
  event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  uid_hash    TEXT,                                   -- NULL for no-read and manual-override events
  tag_id      INTEGER REFERENCES rfid_tag(tag_id),
  gate_id     INTEGER NOT NULL REFERENCES gate(gate_id),
  direction   TEXT NOT NULL CHECK (direction IN ('ENTRY','EXIT')),
  decision    TEXT NOT NULL CHECK (decision IN ('ADMITTED','DENIED')),
  reason      TEXT NOT NULL,
  occurred_at TEXT NOT NULL,                          -- UTC, ISO 8601
  source      TEXT NOT NULL CHECK (source IN ('ONLINE','OFFLINE_SYNC','OVERRIDE')),
  client_ref  TEXT UNIQUE                             -- idempotency key from the gate controller
);
CREATE INDEX IF NOT EXISTS idx_event_uid  ON access_event(uid_hash);
CREATE INDEX IF NOT EXISTS idx_event_time ON access_event(occurred_at);

CREATE TABLE IF NOT EXISTS alert (
  alert_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        INTEGER REFERENCES access_event(event_id),
  type            TEXT NOT NULL,
  message         TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACKNOWLEDGED')),
  acknowledged_by TEXT
);

CREATE TABLE IF NOT EXISTS visitor_pass (
  pass_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  visitor_name TEXT NOT NULL,
  plate        TEXT NOT NULL,
  host         TEXT,
  uid_hash     TEXT NOT NULL,                         -- temporary loan tag
  valid_from   TEXT NOT NULL,
  valid_until  TEXT NOT NULL,
  state        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (state IN ('ACTIVE','CANCELLED')),
  created_by   TEXT
);
CREATE INDEX IF NOT EXISTS idx_pass_uid ON visitor_pass(uid_hash);

CREATE TABLE IF NOT EXISTS user_account (
  user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('ADMIN','SECURITY','ICT')),
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT,
  action   TEXT NOT NULL,
  detail   TEXT,
  at       TEXT NOT NULL
);
