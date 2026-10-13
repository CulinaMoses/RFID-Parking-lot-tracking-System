"""Reference implementation of the gate-controller (edge) logic from Section 4.4.4.

On the real hardware this logic would run on the microcontroller; here it is plain Python so it
can be tested and driven by the simulator and the web demo. It provides:
  * debouncing of repeated reads of the same tag,
  * a local whitelist of hashed tag UIDs so the gate keeps working when the server is unreachable,
  * a buffer of events recorded while offline, replayed to the server on reconnection.
"""
import threading
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from . import service
from .security import hash_uid, normalize_uid


@dataclass
class GateResult:
    action: str                     # ADMIT | DENY | NO_READ | IGNORED
    decision: Optional[str]         # ADMITTED | DENIED | None (ignored)
    barrier_open: bool
    led: str                        # green | red | amber | off
    buzzer: bool
    mode: str                       # ONLINE | OFFLINE
    path: str                       # SERVER (server decided) | LOCAL (controller decided) | NONE
    reason: str
    event_id: Optional[int] = None
    alerts: List[str] = field(default_factory=list)
    buffered: int = 0               # events waiting to be synced after this read


class InProcessLink:
    """Link between a controller and the server logic running in the same process."""

    def __init__(self, db_provider, pepper):
        self._db = db_provider
        self.pepper = pepper
        self.online = True

    def reachable(self):
        return self.online

    def process_event(self, ev):
        if not self.online:
            raise ConnectionError("server unreachable")
        return service.process_event(
            self._db(), self.pepper, uid=ev["uid"], gate_id=ev["gate_id"], direction=ev["direction"],
            ts=ev["ts"], edge_decision=ev["edge_decision"], source="ONLINE", client_ref=ev["ref"])

    def sync(self, events):
        if not self.online:
            raise ConnectionError("server unreachable")
        return service.sync_events(self._db(), self.pepper, events)

    def fetch_whitelist(self, now_iso):
        if not self.online:
            raise ConnectionError("server unreachable")
        return service.whitelist(self._db(), now_iso)


class GateController:
    def __init__(self, gate_id, link, pepper, debounce_s=3.0):
        self.gate_id = gate_id
        self.link = link
        self.pepper = pepper
        self.debounce_s = debounce_s
        self.whitelist = {}          # uid_hash -> (valid_from, valid_until)
        self.buffer = []             # events recorded while the server was unreachable
        self._last_seen = {}         # normalized uid -> datetime of last accepted read
        self._lock = threading.Lock()

    @property
    def mode(self):
        return "ONLINE" if self.link.reachable() else "OFFLINE"

    # -- whitelist ---------------------------------------------------------
    def refresh_whitelist(self, now):
        if not self.link.reachable():
            return False
        try:
            entries = self.link.fetch_whitelist(service.iso(now))
        except ConnectionError:
            return False
        self.whitelist = {e["uid_hash"]: (e["valid_from"], e["valid_until"]) for e in entries}
        return True

    def _locally_valid(self, uid_hash, now):
        window = self.whitelist.get(uid_hash)
        return window is not None and window[0] <= service.iso(now) < window[1]

    # -- event submission ---------------------------------------------------
    def _event(self, uid, direction, now, edge_decision):
        return {"uid": uid, "gate_id": self.gate_id, "direction": direction,
                "ts": service.iso(now), "edge_decision": edge_decision, "ref": uuid.uuid4().hex}

    def _submit(self, ev):
        """Send an event to the server, or buffer it when the server cannot be reached."""
        if self.link.reachable():
            try:
                return self.link.process_event(ev)
            except ConnectionError:
                pass
        self.buffer.append(ev)
        return None

    # -- main entry points ---------------------------------------------------
    def on_tag_detected(self, uid, direction, now):
        with self._lock:
            key = normalize_uid(uid)
            last = self._last_seen.get(key)
            if last is not None and (now - last).total_seconds() < self.debounce_s:
                return GateResult("IGNORED", None, False, "off", False, self.mode, "NONE",
                                  "Repeated read ignored (debounce)", buffered=len(self.buffer))
            self._last_seen[key] = now

            if not self._locally_valid(hash_uid(key, self.pepper), now):
                res = self._submit(self._event(key, direction, now, "DENIED"))
                return GateResult("DENY", "DENIED", False, "red", True, self.mode, "LOCAL",
                                  "Tag not on the gate whitelist or not currently valid",
                                  event_id=res and res["event_id"], alerts=(res or {}).get("alerts", []),
                                  buffered=len(self.buffer))

            if self.link.reachable():
                try:
                    res = self.link.process_event(self._event(key, direction, now, None))
                    ok = res["decision"] == "ADMITTED"
                    return GateResult("ADMIT" if ok else "DENY", res["decision"], ok,
                                      "green" if ok else "red", not ok, "ONLINE", "SERVER",
                                      res["reason"], event_id=res["event_id"], alerts=res["alerts"],
                                      buffered=len(self.buffer))
                except ConnectionError:
                    pass   # link dropped mid-request: fall through to the offline path

            self.buffer.append(self._event(key, direction, now, "ADMITTED"))
            return GateResult("ADMIT", "ADMITTED", True, "green", False, "OFFLINE", "LOCAL",
                              "Admitted from local whitelist (server offline); event buffered",
                              buffered=len(self.buffer))

    def on_no_read(self, direction, now):
        """A vehicle is at the gate but no tag could be read."""
        with self._lock:
            res = self._submit(self._event(None, direction, now, "DENIED"))
            return GateResult("NO_READ", "DENIED", False, "amber", True, self.mode, "LOCAL",
                              "No tag read; manual check required",
                              event_id=res and res["event_id"], buffered=len(self.buffer))

    def sync(self, now):
        """Replay buffered events and refresh the whitelist once the server is reachable."""
        with self._lock:
            if not self.link.reachable():
                return {"synced": 0, "pending": len(self.buffer), "mode": "OFFLINE"}
            pending = list(self.buffer)
            if pending:
                try:
                    self.link.sync(pending)
                except ConnectionError:
                    return {"synced": 0, "pending": len(self.buffer), "mode": "OFFLINE"}
                del self.buffer[:len(pending)]
            self.refresh_whitelist(now)
            return {"synced": len(pending), "pending": len(self.buffer), "mode": "ONLINE"}
