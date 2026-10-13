"""Server-side business logic: registration, access decisions, occupancy, alerts, reports.

Every function takes an open sqlite3 connection, so the same code serves the Flask API,
the gate-controller link and the simulator.
"""
import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from .security import hash_uid

FMT = "%Y-%m-%dT%H:%M:%S"
CATEGORIES = ("STAFF", "STUDENT", "CONTRACTOR", "OTHER")
VEHICLE_STATUSES = ("ACTIVE", "SUSPENDED", "BLACKLISTED")
TAG_STATES = ("ACTIVE", "SUSPENDED", "REVOKED")
ROLES = ("ADMIN", "SECURITY", "ICT")


def iso(dt):
    return dt.strftime(FMT)


def parse(s):
    return datetime.strptime(s, FMT)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _plate(p):
    p = (p or "").strip().upper().replace(" ", "")
    if not p:
        raise ValueError("Plate number is required")
    return p


# ---------------------------------------------------------------- audit ----
def audit(db, username, action, detail="", now=None):
    db.execute("INSERT INTO audit_log(username, action, detail, at) VALUES (?,?,?,?)",
               (username, action, detail, iso(now or utcnow())))
    db.commit()


# --------------------------------------------------- registration (FR1/2) ----
def create_vehicle(db, owner, plate, make_model="", colour=""):
    full_name = (owner.get("full_name") or "").strip()
    category = (owner.get("category") or "").upper()
    if not full_name:
        raise ValueError("Owner name is required")
    if category not in CATEGORIES:
        raise ValueError("Owner category must be one of " + ", ".join(CATEGORIES))
    plate = _plate(plate)
    try:
        with db:
            oid = db.execute(
                "INSERT INTO owner(full_name, category, phone, department) VALUES (?,?,?,?)",
                (full_name, category, owner.get("phone", ""), owner.get("department", ""))).lastrowid
            vid = db.execute(
                "INSERT INTO vehicle(owner_id, plate, make_model, colour) VALUES (?,?,?,?)",
                (oid, plate, make_model, colour)).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Plate number %s is already registered" % plate)
    return {"owner_id": oid, "vehicle_id": vid}


def set_vehicle_status(db, vehicle_id, status):
    status = (status or "").upper()
    if status not in VEHICLE_STATUSES:
        raise ValueError("Status must be one of " + ", ".join(VEHICLE_STATUSES))
    with db:
        cur = db.execute("UPDATE vehicle SET status=? WHERE vehicle_id=?", (status, vehicle_id))
    if cur.rowcount == 0:
        raise ValueError("Vehicle not found")


def issue_tag(db, pepper, vehicle_id, uid, expires_at=None, now=None):
    now = now or utcnow()
    if db.execute("SELECT 1 FROM vehicle WHERE vehicle_id=?", (vehicle_id,)).fetchone() is None:
        raise ValueError("Vehicle not found")
    uid_hash = hash_uid(uid, pepper)
    expires = expires_at or iso(now + timedelta(days=365))
    parse(expires)  # validates format
    if db.execute("SELECT 1 FROM visitor_pass WHERE uid_hash=?", (uid_hash,)).fetchone():
        raise ValueError("This tag is already used for a visitor pass")
    try:
        with db:
            tid = db.execute(
                "INSERT INTO rfid_tag(vehicle_id, uid_hash, issued_at, expires_at) VALUES (?,?,?,?)",
                (vehicle_id, uid_hash, iso(now), expires)).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("This tag is already assigned to a vehicle")
    return tid


def set_tag_state(db, tag_id, state):
    state = (state or "").upper()
    if state not in TAG_STATES:
        raise ValueError("State must be one of " + ", ".join(TAG_STATES))
    with db:
        cur = db.execute("UPDATE rfid_tag SET state=? WHERE tag_id=?", (state, tag_id))
    if cur.rowcount == 0:
        raise ValueError("Tag not found")


# ------------------------------------------------------ visitors (FR7) ----
def issue_visitor_pass(db, pepper, visitor_name, plate, host, uid, valid_from, valid_until, created_by=None):
    if not (visitor_name or "").strip():
        raise ValueError("Visitor name is required")
    if parse(valid_until) <= parse(valid_from):
        raise ValueError("Pass must end after it starts")
    uid_hash = hash_uid(uid, pepper)
    if db.execute("SELECT 1 FROM rfid_tag WHERE uid_hash=?", (uid_hash,)).fetchone():
        raise ValueError("This tag is already assigned to a registered vehicle")
    with db:
        return db.execute(
            "INSERT INTO visitor_pass(visitor_name, plate, host, uid_hash, valid_from, valid_until, created_by)"
            " VALUES (?,?,?,?,?,?,?)",
            (visitor_name.strip(), _plate(plate), host or "", uid_hash, valid_from, valid_until, created_by)).lastrowid


def cancel_visitor_pass(db, pass_id):
    with db:
        cur = db.execute("UPDATE visitor_pass SET state='CANCELLED' WHERE pass_id=?", (pass_id,))
    if cur.rowcount == 0:
        raise ValueError("Pass not found")


# ------------------------------------------------- access decision (FR3/4) ----
def evaluate(db, uid_hash, ts):
    """Decide admit/deny for a tag hash at time ts (ISO string). Returns a dict."""
    def verdict(decision, reason, alert_type=None, tag_id=None):
        return {"decision": decision, "reason": reason, "alert_type": alert_type, "tag_id": tag_id}

    row = db.execute(
        "SELECT t.tag_id, t.state, t.expires_at, v.status AS vstatus, v.plate "
        "FROM rfid_tag t JOIN vehicle v ON v.vehicle_id = t.vehicle_id WHERE t.uid_hash=?",
        (uid_hash,)).fetchone()
    if row:
        tid = row["tag_id"]
        if row["state"] == "REVOKED":
            return verdict("DENIED", "Tag revoked (%s)" % row["plate"], "REVOKED_TAG", tid)
        if row["state"] == "SUSPENDED":
            return verdict("DENIED", "Tag suspended (%s)" % row["plate"], "SUSPENDED", tid)
        if row["expires_at"] <= ts:
            return verdict("DENIED", "Tag expired (%s)" % row["plate"], "EXPIRED_TAG", tid)
        if row["vstatus"] == "BLACKLISTED":
            return verdict("DENIED", "Vehicle blacklisted (%s)" % row["plate"], "BLACKLISTED", tid)
        if row["vstatus"] == "SUSPENDED":
            return verdict("DENIED", "Vehicle suspended (%s)" % row["plate"], "SUSPENDED", tid)
        return verdict("ADMITTED", "Registered vehicle (%s)" % row["plate"], None, tid)

    p = db.execute("SELECT * FROM visitor_pass WHERE uid_hash=? ORDER BY pass_id DESC LIMIT 1",
                   (uid_hash,)).fetchone()
    if p:
        if p["state"] != "ACTIVE":
            return verdict("DENIED", "Visitor pass cancelled (%s)" % p["plate"], "EXPIRED_PASS")
        if not (p["valid_from"] <= ts < p["valid_until"]):
            return verdict("DENIED", "Visitor pass outside validity window (%s)" % p["plate"], "EXPIRED_PASS")
        return verdict("ADMITTED", "Visitor pass (%s)" % p["plate"])
    return verdict("DENIED", "Unregistered tag", "UNREGISTERED")


def _add_alert(db, event_id, alert_type, message, ts):
    db.execute("INSERT INTO alert(event_id, type, message, created_at) VALUES (?,?,?,?)",
               (event_id, alert_type, message, ts))


def _adjust_lot(db, gate_id, delta):
    lot = db.execute("SELECT p.lot_id, p.capacity, p.current_count FROM gate g "
                     "JOIN parking_lot p ON p.lot_id = g.lot_id WHERE g.gate_id=?", (gate_id,)).fetchone()
    new = max(0, lot["current_count"] + delta)
    db.execute("UPDATE parking_lot SET current_count=? WHERE lot_id=?", (new, lot["lot_id"]))
    return new, lot["capacity"]


def process_event(db, pepper, *, uid, gate_id, direction, ts, edge_decision=None,
                  source="ONLINE", client_ref=None):
    """Validate (or record) one gate event, log it, update occupancy and raise alerts.

    edge_decision=None  -> the server decides (normal online path).
    edge_decision=...   -> the gate controller already decided (local deny, offline admit,
                           no-read); the server records it and cross-checks it.
    uid=None            -> the reader detected a vehicle but could not read a tag.
    """
    direction = (direction or "").upper()
    if direction not in ("ENTRY", "EXIT"):
        raise ValueError("Direction must be ENTRY or EXIT")
    if edge_decision not in (None, "ADMITTED", "DENIED"):
        raise ValueError("Invalid edge decision")
    if db.execute("SELECT 1 FROM gate WHERE gate_id=?", (gate_id,)).fetchone() is None:
        raise ValueError("Unknown gate")
    parse(ts)

    if client_ref:  # idempotent: a re-sent event returns the original result
        old = db.execute("SELECT event_id, decision, reason FROM access_event WHERE client_ref=?",
                         (client_ref,)).fetchone()
        if old:
            return {"event_id": old["event_id"], "decision": old["decision"], "reason": old["reason"],
                    "alerts": [], "barrier": "OPEN" if old["decision"] == "ADMITTED" else "CLOSED",
                    "duplicate": True}

    uid_hash = hash_uid(uid, pepper) if uid else None
    alerts = []   # (type, message)
    verdict = evaluate(db, uid_hash, ts) if uid_hash else None

    if uid_hash is None:
        decision, reason = "DENIED", "No tag read; manual check required"
    elif edge_decision is None:
        decision, reason = verdict["decision"], verdict["reason"]
        if decision == "DENIED":
            alerts.append((verdict["alert_type"], verdict["reason"]))
    elif edge_decision == "ADMITTED":
        decision = "ADMITTED"
        reason = "Admitted at gate (local whitelist); server check: " + verdict["reason"]
        if verdict["decision"] == "DENIED":
            alerts.append(("OFFLINE_MISMATCH",
                           "Admitted by gate controller but server now says: " + verdict["reason"]))
    else:
        decision = "DENIED"
        reason = "Denied at gate: " + verdict["reason"]
        if verdict["decision"] == "DENIED":
            alerts.append((verdict["alert_type"], verdict["reason"]))
        else:
            alerts.append(("WHITELIST_STALE", "Gate whitelist out of date for a valid tag"))

    tag_id = verdict["tag_id"] if verdict else None
    lot_count = None
    with db:
        try:
            event_id = db.execute(
                "INSERT INTO access_event(uid_hash, tag_id, gate_id, direction, decision, reason,"
                " occurred_at, source, client_ref) VALUES (?,?,?,?,?,?,?,?,?)",
                (uid_hash, tag_id, gate_id, direction, decision, reason, ts, source, client_ref)).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("Duplicate event reference")

        if decision == "ADMITTED" and uid_hash:
            inside = _is_inside_before(db, uid_hash, event_id)
            if direction == "ENTRY":
                if inside:
                    alerts.append(("DUPLICATE_READ", "Entry read while the vehicle is already recorded inside"))
                else:
                    lot_count, cap = _adjust_lot(db, gate_id, +1)
                    if lot_count > cap:
                        alerts.append(("LOT_FULL", "Lot over capacity (%d/%d)" % (lot_count, cap)))
            else:
                if not inside:
                    alerts.append(("UNMATCHED_EXIT", "Exit read with no matching entry on record"))
                else:
                    lot_count, _ = _adjust_lot(db, gate_id, -1)
        for a_type, msg in alerts:
            _add_alert(db, event_id, a_type, msg, ts)

    return {"event_id": event_id, "decision": decision, "reason": reason,
            "alerts": [a for a, _ in alerts], "lot_count": lot_count,
            "barrier": "OPEN" if decision == "ADMITTED" else "CLOSED", "duplicate": False}


def _is_inside_before(db, uid_hash, event_id):
    row = db.execute(
        "SELECT direction FROM access_event WHERE uid_hash=? AND decision='ADMITTED' AND event_id<? "
        "ORDER BY event_id DESC LIMIT 1", (uid_hash, event_id)).fetchone()
    return bool(row and row["direction"] == "ENTRY")


def sync_events(db, pepper, events):
    """Replay events buffered by an offline gate controller, oldest first."""
    results = []
    for ev in sorted(events, key=lambda e: e["ts"]):
        results.append(process_event(
            db, pepper, uid=ev.get("uid"), gate_id=ev["gate_id"], direction=ev["direction"],
            ts=ev["ts"], edge_decision=ev.get("edge_decision"), source="OFFLINE_SYNC",
            client_ref=ev.get("ref")))
    return results


def whitelist(db, now_iso):
    """Tag hashes the gate controller may admit locally (active, unexpired)."""
    rows = db.execute(
        "SELECT t.uid_hash, t.issued_at AS valid_from, t.expires_at AS valid_until "
        "FROM rfid_tag t JOIN vehicle v ON v.vehicle_id=t.vehicle_id "
        "WHERE t.state='ACTIVE' AND v.status='ACTIVE' AND t.expires_at > ?", (now_iso,)).fetchall()
    out = [dict(r) for r in rows]
    rows = db.execute("SELECT uid_hash, valid_from, valid_until FROM visitor_pass "
                      "WHERE state='ACTIVE' AND valid_until > ?", (now_iso,)).fetchall()
    out += [dict(r) for r in rows]
    return out


# ---------------------------------------------- override (FR9), alerts ----
def manual_override(db, gate_id, direction, note, username, ts):
    direction = (direction or "").upper()
    if direction not in ("ENTRY", "EXIT"):
        raise ValueError("Direction must be ENTRY or EXIT")
    if not (note or "").strip():
        raise ValueError("A reason is required for a manual override")
    if db.execute("SELECT 1 FROM gate WHERE gate_id=?", (gate_id,)).fetchone() is None:
        raise ValueError("Unknown gate")
    reason = "Manual override by %s: %s" % (username, note.strip())
    with db:
        eid = db.execute(
            "INSERT INTO access_event(uid_hash, tag_id, gate_id, direction, decision, reason, occurred_at, source)"
            " VALUES (NULL, NULL, ?, ?, 'ADMITTED', ?, ?, 'OVERRIDE')",
            (gate_id, direction, reason, ts)).lastrowid
        count, _ = _adjust_lot(db, gate_id, +1 if direction == "ENTRY" else -1)
        _add_alert(db, eid, "MANUAL_OVERRIDE", reason, ts)
    audit(db, username, "MANUAL_OVERRIDE", "gate=%s direction=%s note=%s" % (gate_id, direction, note.strip()))
    return {"event_id": eid, "lot_count": count}


def acknowledge_alert(db, alert_id, username):
    with db:
        cur = db.execute("UPDATE alert SET status='ACKNOWLEDGED', acknowledged_by=? WHERE alert_id=?",
                         (username, alert_id))
    if cur.rowcount == 0:
        raise ValueError("Alert not found")


# ------------------------------------------------- users / accounts (FR11) ----
def create_user(db, username, password, role, now=None):
    username = (username or "").strip()
    role = (role or "").upper()
    if not (3 <= len(username) <= 32) or not username.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Username must be 3-32 letters, digits, '.' or '_'")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    if role not in ROLES:
        raise ValueError("Role must be one of " + ", ".join(ROLES))
    try:
        with db:
            return db.execute(
                "INSERT INTO user_account(username, password_hash, role, created_at) VALUES (?,?,?,?)",
                (username, generate_password_hash(password), role, iso(now or utcnow()))).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Username already exists")


# ------------------------------------------- monitoring and reports (FR6/10) ----
def lots(db):
    return [dict(r) for r in db.execute(
        "SELECT lot_id, name, capacity, current_count FROM parking_lot ORDER BY lot_id")]


def dashboard(db, now):
    today = iso(now).split("T")[0]
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    return {
        "registered_vehicles": one("SELECT COUNT(*) FROM vehicle"),
        "vehicles_inside": one("SELECT COALESCE(SUM(current_count),0) FROM parking_lot"),
        "open_alerts": one("SELECT COUNT(*) FROM alert WHERE status='OPEN'"),
        "admitted_today": one("SELECT COUNT(*) FROM access_event WHERE decision='ADMITTED' AND occurred_at>=?", today),
        "denied_today": one("SELECT COUNT(*) FROM access_event WHERE decision='DENIED' AND occurred_at>=?", today),
        "lots": lots(db),
    }


EVENT_SQL = (
    "SELECT e.event_id, e.occurred_at, g.name AS gate, e.direction, e.decision, e.reason, e.source,"
    " COALESCE(v.plate, (SELECT plate FROM visitor_pass WHERE uid_hash=e.uid_hash ORDER BY pass_id DESC LIMIT 1)) AS plate "
    "FROM access_event e JOIN gate g ON g.gate_id=e.gate_id "
    "LEFT JOIN rfid_tag t ON t.tag_id=e.tag_id LEFT JOIN vehicle v ON v.vehicle_id=t.vehicle_id "
)


def list_events(db, limit=50, decision=None, start=None, end=None):
    where, args = [], []
    if decision:
        where.append("e.decision=?")
        args.append(decision.upper())
    if start:
        where.append("e.occurred_at>=?")
        args.append(start)
    if end:
        where.append("e.occurred_at<?")
        args.append(end)
    sql = EVENT_SQL + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY e.event_id DESC LIMIT ?"
    return [dict(r) for r in db.execute(sql, args + [int(limit)])]


def _csv_safe(value):
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s   # block spreadsheet formula injection


def events_csv(db, start=None, end=None):
    rows = list_events(db, limit=100000, start=start, end=end)
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["event_id", "occurred_at", "gate", "direction", "decision", "plate", "reason", "source"]
    w.writerow(cols)
    for r in reversed(rows):
        w.writerow([_csv_safe(r[c]) for c in cols])
    return buf.getvalue()
