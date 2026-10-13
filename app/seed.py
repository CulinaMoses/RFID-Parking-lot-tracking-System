"""Demo data. Run:  python -m app.seed   (creates instance/parking.db with demo users and vehicles).

All names, plates and tag UIDs below are made-up demo values.
"""
import os
import sys
from datetime import datetime, timedelta

from . import service
from .db import connect, init_schema

CATS = ["STAFF", "STUDENT", "STAFF", "CONTRACTOR", "STUDENT"]


def seed_demo(db, pepper, now, vehicles=40):
    """Create one lot, one gate and a deterministic set of registered vehicles.

    Returns {'valid': [...uids], 'expired': [...], 'revoked': [...], 'blacklisted': [...]}.
    """
    with db:
        lot = db.execute("INSERT INTO parking_lot(name, capacity) VALUES ('Lot A', 200)").lastrowid
        db.execute("INSERT INTO gate(name, lot_id) VALUES ('Main Gate', ?)", (lot,))
    groups = {"valid": [], "expired": [], "revoked": [], "blacklisted": []}

    def add(i, kind):
        uid = "E2801160%08X" % (0x1000 + i)
        v = service.create_vehicle(
            db, {"full_name": "Demo Owner %02d" % i, "category": CATS[i % len(CATS)],
                 "department": "Demo Dept"},
            "AB%03dUI" % (100 + i), "Demo Car", "Grey")
        expires = service.iso(now - timedelta(days=30)) if kind == "expired" else None
        tid = service.issue_tag(db, pepper, v["vehicle_id"], uid, expires, now)
        if kind == "revoked":
            service.set_tag_state(db, tid, "REVOKED")
        if kind == "blacklisted":
            service.set_vehicle_status(db, v["vehicle_id"], "BLACKLISTED")
        groups[kind].append(uid)

    for i in range(vehicles):
        add(i, "valid")
    for i, kind in enumerate(["expired"] * 3 + ["revoked"] * 3 + ["blacklisted"] * 3):
        add(vehicles + i, kind)
    return groups


def main():
    from . import create_app
    app = create_app()
    pepper = app.config["PEPPER"]
    db = connect(app.config["DATABASE"])
    if db.execute("SELECT COUNT(*) FROM vehicle").fetchone()[0]:
        print("Database already has data; delete instance/parking.db to re-seed.")
        return
    now = service.utcnow()
    groups = seed_demo(db, pepper, now)
    pw = os.environ.get("RFID_DEMO_PASSWORD", "ChangeMe!2026")
    for name, role in (("admin", "ADMIN"), ("gate1", "SECURITY"), ("ict1", "ICT")):
        service.create_user(db, name, pw, role, now)
    with open(os.path.join(app.instance_path, "demo_tags.txt"), "w") as f:
        for kind, uids in groups.items():
            for uid in uids:
                f.write("%s\t%s\n" % (kind, uid))
    print("Seeded. Users: admin, gate1, ict1  password: %s  (change these!)" % pw)
    print("Demo tag UIDs written to instance/demo_tags.txt")


if __name__ == "__main__":
    sys.exit(main())
