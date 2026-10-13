"""Functional tests T01-T17, mapped to the requirements in Section 4.3 of the report.

Run:  python -m unittest discover -v
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app import create_app, service
from app.db import connect
from app.gate_controller import GateController, InProcessLink
from app.security import hash_uid

PW = "Test!Passw0rd"
NOW = datetime(2026, 3, 2, 8, 0, 0)


def ts(dt):
    return service.iso(dt)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "t.db")
        self.app = create_app({"DATABASE": self.path, "TESTING": True,
                               "PEPPER": "test-pepper", "GATE_API_KEY": "gk"})
        self.pepper = "test-pepper"
        self.db = connect(self.path)
        with self.db:
            lot = self.db.execute("INSERT INTO parking_lot(name, capacity) VALUES ('Lot A', 2)").lastrowid
            self.db.execute("INSERT INTO gate(name, lot_id) VALUES ('Main Gate', ?)", (lot,))
        for name, role in (("admin", "ADMIN"), ("guard", "SECURITY"), ("ictstaff", "ICT")):
            service.create_user(self.db, name, PW, role, NOW)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def client(self, user=None):
        c = self.app.test_client()
        if user:
            r = c.post("/api/auth/login", json={"username": user, "password": PW})
            self.assertEqual(r.status_code, 200)
        return c

    def vehicle(self, plate="AB123UI", uid="E200AA01", expires=None, **kw):
        v = service.create_vehicle(self.db, {"full_name": "Test Owner", "category": "STAFF"}, plate)
        tid = service.issue_tag(self.db, self.pepper, v["vehicle_id"], uid, expires, NOW - timedelta(days=1))
        return v["vehicle_id"], tid

    def event(self, uid, direction="ENTRY", at=NOW, **kw):
        return service.process_event(self.db, self.pepper, uid=uid, gate_id=1, direction=direction,
                                     ts=ts(at), **kw)

    def lot_count(self):
        return self.db.execute("SELECT current_count FROM parking_lot").fetchone()[0]

    def alert_types(self):
        return [r[0] for r in self.db.execute("SELECT type FROM alert ORDER BY alert_id")]

    def controller(self):
        link = InProcessLink(lambda: self.db, self.pepper)
        gc = GateController(1, link, self.pepper)
        gc.refresh_whitelist(NOW)
        return gc, link


class TestRegistration(Base):
    def test_T01_register_owner_and_vehicle(self):          # FR1
        c = self.client("admin")
        r = c.post("/api/vehicles", json={"plate": "ab 123 ui", "make_model": "Corolla", "colour": "Blue",
                                          "owner": {"full_name": "Ada Obi", "category": "student"}})
        self.assertEqual(r.status_code, 201)
        rows = c.get("/api/vehicles").get_json()
        self.assertEqual(rows[0]["plate"], "AB123UI")           # normalised
        self.assertEqual(rows[0]["category"], "STUDENT")
        dup = c.post("/api/vehicles", json={"plate": "AB123UI",
                                            "owner": {"full_name": "Other", "category": "STAFF"}})
        self.assertEqual(dup.status_code, 400)                  # duplicate plate rejected

    def test_T02_issue_tag_to_vehicle(self):                # FR2
        vid, _ = self.vehicle()
        c = self.client("admin")
        r = c.post("/api/vehicles/%d/tags" % vid, json={"uid": "e2 00 bb 02"})
        self.assertEqual(r.status_code, 201)
        again = c.post("/api/vehicles/%d/tags" % vid, json={"uid": "E200BB02"})
        self.assertEqual(again.status_code, 400)                # same UID twice rejected (normalised)
        self.assertEqual(self.event("E200BB02")["decision"], "ADMITTED")

    def test_T03_suspend_and_revoke_block_entry(self):      # FR2/FR4
        _, tid = self.vehicle()
        service.set_tag_state(self.db, tid, "SUSPENDED")
        self.assertEqual(self.event("E200AA01")["decision"], "DENIED")
        service.set_tag_state(self.db, tid, "REVOKED")
        r = self.event("E200AA01", at=NOW + timedelta(minutes=1))
        self.assertEqual(r["decision"], "DENIED")
        self.assertIn("REVOKED_TAG", r["alerts"])
        service.set_tag_state(self.db, tid, "ACTIVE")
        self.assertEqual(self.event("E200AA01", at=NOW + timedelta(minutes=2))["decision"], "ADMITTED")


class TestAccess(Base):
    def test_T04_valid_tag_admitted(self):                  # FR3/FR4
        self.vehicle()
        gc, _ = self.controller()
        res = gc.on_tag_detected("E200AA01", "ENTRY", NOW)
        self.assertEqual((res.decision, res.barrier_open, res.led), ("ADMITTED", True, "green"))
        self.assertEqual(res.path, "SERVER")

    def test_T05_unregistered_tag_denied_with_alert(self):  # FR4/FR8
        gc, _ = self.controller()
        res = gc.on_tag_detected("DEADBEEF", "ENTRY", NOW)
        self.assertEqual((res.decision, res.barrier_open, res.led, res.buzzer), ("DENIED", False, "red", True))
        self.assertIn("UNREGISTERED", res.alerts)

    def test_T06_expired_tag_denied_with_alert(self):       # FR8
        self.vehicle(expires=ts(NOW - timedelta(days=1)))
        r = self.event("E200AA01")
        self.assertEqual(r["decision"], "DENIED")
        self.assertEqual(r["alerts"], ["EXPIRED_TAG"])

    def test_T07_blacklisted_vehicle_denied_with_alert(self):  # FR8
        vid, _ = self.vehicle()
        service.set_vehicle_status(self.db, vid, "BLACKLISTED")
        r = self.event("E200AA01")
        self.assertEqual((r["decision"], r["alerts"]), ("DENIED", ["BLACKLISTED"]))

    def test_T08_events_logged_with_details(self):          # FR5
        self.vehicle()
        self.event("E200AA01", "ENTRY")
        self.event("E200AA01", "EXIT", NOW + timedelta(hours=2))
        self.event("UNKNOWN1", "ENTRY", NOW + timedelta(hours=3))
        rows = service.list_events(self.db)
        self.assertEqual(len(rows), 3)
        newest, oldest = rows[0], rows[-1]
        self.assertEqual((newest["decision"], newest["gate"], newest["direction"]), ("DENIED", "Main Gate", "ENTRY"))
        self.assertEqual((oldest["plate"], oldest["occurred_at"]), ("AB123UI", ts(NOW)))

    def test_T09_occupancy_updates(self):                   # FR6
        self.vehicle("AA1", "E1")
        self.vehicle("BB2", "E2")
        self.vehicle("CC3", "E3")
        self.event("E1"); self.event("E2", at=NOW + timedelta(seconds=5))
        self.assertEqual(self.lot_count(), 2)
        self.event("E1", "EXIT", NOW + timedelta(minutes=5))
        self.assertEqual(self.lot_count(), 1)
        self.event("E3", at=NOW + timedelta(minutes=6)); self.event("E1", at=NOW + timedelta(minutes=7))
        self.assertEqual(self.lot_count(), 3)
        self.assertIn("LOT_FULL", self.alert_types())            # capacity is 2
        dash = self.client("ictstaff").get("/api/dashboard").get_json()
        self.assertEqual(dash["vehicles_inside"], 3)

    def test_T10_duplicate_reads(self):                     # FR8
        self.vehicle()
        gc, _ = self.controller()
        first = gc.on_tag_detected("E200AA01", "ENTRY", NOW)
        again = gc.on_tag_detected("e2-00-aa-01", "ENTRY", NOW + timedelta(seconds=1))
        self.assertEqual(first.decision, "ADMITTED")
        self.assertEqual(again.action, "IGNORED")                # debounced at the gate
        self.assertEqual(self.lot_count(), 1)
        self.assertEqual(len(service.list_events(self.db)), 1)
        later = gc.on_tag_detected("E200AA01", "ENTRY", NOW + timedelta(minutes=2))  # second entry, no exit
        self.assertEqual(later.decision, "ADMITTED")
        self.assertIn("DUPLICATE_READ", later.alerts)
        self.assertEqual(self.lot_count(), 1)                    # not double counted

    def test_T11_visitor_pass(self):                        # FR7
        service.issue_visitor_pass(self.db, self.pepper, "Visitor", "VV1", "Dr X", "VISIT01",
                                   ts(NOW), ts(NOW + timedelta(hours=4)))
        self.assertEqual(self.event("VISIT01", at=NOW + timedelta(hours=1))["decision"], "ADMITTED")
        late = self.event("VISIT01", "EXIT", NOW + timedelta(hours=5))
        self.assertEqual((late["decision"], late["alerts"]), ("DENIED", ["EXPIRED_PASS"]))
        c = self.client("guard")
        self.assertEqual(c.get("/api/visitor-passes").status_code, 200)

    def test_T12_manual_override_logged_and_audited(self):  # FR9
        c = self.client("guard")
        r = c.post("/api/gate/override", json={"gate_id": 1, "direction": "ENTRY", "note": "Tag damaged, ID checked"})
        self.assertEqual(r.status_code, 201)
        ev = service.list_events(self.db)[0]
        self.assertEqual((ev["source"], ev["decision"]), ("OVERRIDE", "ADMITTED"))
        self.assertIn("guard", ev["reason"])
        self.assertEqual(self.lot_count(), 1)
        self.assertIn("MANUAL_OVERRIDE", self.alert_types())
        actions = [r[0] for r in self.db.execute("SELECT action FROM audit_log")]
        self.assertIn("MANUAL_OVERRIDE", actions)
        bad = c.post("/api/gate/override", json={"gate_id": 1, "direction": "ENTRY", "note": " "})
        self.assertEqual(bad.status_code, 400)                   # a reason is mandatory


class TestOffline(Base):
    def test_T13_offline_gate_buffers_and_syncs(self):      # NFR2
        self.vehicle("AA1", "E1"); self.vehicle("BB2", "E2")
        gc, link = self.controller()
        link.online = False
        a = gc.on_tag_detected("E1", "ENTRY", NOW)
        b = gc.on_tag_detected("UNKNOWN", "ENTRY", NOW + timedelta(seconds=30))
        c = gc.on_tag_detected("E2", "ENTRY", NOW + timedelta(seconds=60))
        self.assertEqual((a.decision, a.mode, a.path), ("ADMITTED", "OFFLINE", "LOCAL"))
        self.assertEqual(b.decision, "DENIED")
        self.assertEqual(c.buffered, 3)
        self.assertEqual(len(service.list_events(self.db)), 0)   # nothing reached the server yet
        link.online = True
        out = gc.sync(NOW + timedelta(minutes=5))
        self.assertEqual((out["synced"], out["pending"]), (3, 0))
        rows = service.list_events(self.db)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["source"] == "OFFLINE_SYNC" for r in rows))
        self.assertEqual(self.lot_count(), 2)
        again = gc.sync(NOW + timedelta(minutes=6))              # nothing duplicated
        self.assertEqual(len(service.list_events(self.db)), 3)
        self.assertEqual(again["synced"], 0)

    def test_T13b_replayed_event_is_idempotent(self):
        self.vehicle()
        ev = {"uid": "E200AA01", "gate_id": 1, "direction": "ENTRY", "ts": ts(NOW), "edge_decision": "ADMITTED", "ref": "r1"}
        service.sync_events(self.db, self.pepper, [ev])
        service.sync_events(self.db, self.pepper, [ev])
        self.assertEqual(len(service.list_events(self.db)), 1)
        self.assertEqual(self.lot_count(), 1)

    def test_T13c_offline_admit_of_since_revoked_tag_raises_alert(self):
        _, tid = self.vehicle()
        gc, link = self.controller()
        link.online = False
        self.assertEqual(gc.on_tag_detected("E200AA01", "ENTRY", NOW).decision, "ADMITTED")
        service.set_tag_state(self.db, tid, "REVOKED")           # revoked while the gate was offline
        link.online = True
        gc.sync(NOW + timedelta(minutes=1))
        self.assertIn("OFFLINE_MISMATCH", self.alert_types())


class TestSecurity(Base):
    def test_T14_authentication_and_roles(self):            # FR11 / NFR4
        anon = self.app.test_client()
        self.assertEqual(anon.get("/api/dashboard").status_code, 401)
        self.assertEqual(anon.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code, 401)
        guard = self.client("guard")
        self.assertEqual(guard.post("/api/users", json={"username": "x1234", "password": PW, "role": "ICT"}).status_code, 403)
        self.assertEqual(guard.post("/api/vehicles", json={"plate": "Z1", "owner": {}}).status_code, 403)
        self.assertEqual(guard.get("/api/audit").status_code, 403)
        ict = self.client("ictstaff")
        self.assertEqual(ict.post("/api/users", json={"username": "newguard", "password": PW, "role": "SECURITY"}).status_code, 201)
        self.assertEqual(ict.post("/api/users", json={"username": "weakpw", "password": "123", "role": "SECURITY"}).status_code, 400)
        self.assertEqual(ict.get("/api/vehicles").status_code, 403)
        # gate API needs the gate key
        self.assertEqual(anon.get("/api/gate/whitelist").status_code, 401)
        self.assertEqual(anon.get("/api/gate/whitelist", headers={"X-Gate-Key": "gk"}).status_code, 200)

    def test_T15_audit_log_records_actions(self):           # FR11
        admin = self.client("admin")
        admin.post("/api/vehicles", json={"plate": "AUD1", "owner": {"full_name": "A", "category": "STAFF"}})
        self.app.test_client().post("/api/auth/login", json={"username": "admin", "password": "nope"})
        rows = self.client("ictstaff").get("/api/audit").get_json()
        actions = [r["action"] for r in rows]
        for expected in ("LOGIN", "VEHICLE_REGISTERED", "LOGIN_FAILED"):
            self.assertIn(expected, actions)

    def test_T16_uids_and_passwords_stored_hashed(self):    # NFR4/NFR5
        self.vehicle(uid="E200SECRET99")
        self.event("E200SECRET99")
        self.event("E200UNKNOWN77", at=NOW + timedelta(seconds=9))
        with open(self.path, "rb") as fh:
            raw = fh.read()
        self.assertNotIn(b"E200SECRET99", raw)
        self.assertNotIn(b"E200UNKNOWN77", raw)
        self.assertIn(hash_uid("E200SECRET99", self.pepper).encode(), raw)
        self.assertNotIn(PW.encode(), raw)
        hashes = [r[0] for r in self.db.execute("SELECT password_hash FROM user_account")]
        self.assertTrue(all(h.startswith(("scrypt:", "pbkdf2:")) for h in hashes))

    def test_T17_csv_report_export(self):                   # FR10
        self.vehicle("=CMD1", "E9")
        self.event("E9"); self.event("NOPE", at=NOW + timedelta(seconds=9))
        guard = self.client("guard")
        r = guard.get("/api/reports/events.csv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "text/csv")
        lines = r.get_data(as_text=True).strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("event_id,occurred_at,gate"))
        self.assertIn("'=CMD1", lines[1])                        # formula injection neutralised
        self.assertEqual(self.client("ictstaff").get("/api/reports/events.csv").status_code, 403)

    def test_T18_gate_api_event_and_demo_endpoints(self):
        self.vehicle()
        c = self.app.test_client()
        r = c.post("/api/gate/event", headers={"X-Gate-Key": "gk"},
                   json={"uid": "E200AA01", "gate_id": 1, "direction": "ENTRY", "ts": ts(NOW), "ref": "x1"})
        self.assertEqual(r.get_json()["decision"], "ADMITTED")
        g = self.client("guard")
        self.assertEqual(g.post("/api/sim/read", json={"gate_id": 1, "direction": "ENTRY", "uid": "NOPE"}).get_json()["decision"], "DENIED")
        self.assertEqual(g.post("/api/sim/network", json={"gate_id": 1, "online": False}).get_json()["mode"], "OFFLINE")
        self.assertEqual(g.post("/api/sim/sync", json={"gate_id": 1}).get_json()["mode"], "OFFLINE")
        self.assertEqual(g.post("/api/sim/network", json={"gate_id": 1, "online": True}).get_json()["mode"], "ONLINE")


if __name__ == "__main__":
    unittest.main()
