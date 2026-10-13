"""Tag-read simulator that reproduces the 12 evaluation scenarios of Section 4.5.

Run:  python -m app.simulator --out results
Each scenario drives the real GateController and server logic against an in-memory database, so
the decisions, alerts, occupancy and offline buffering are the code's actual behaviour. Only the
radio read and the network/processing delays are modelled (parameters below), so identification
and processing times are *modelled* values, not measurements of real hardware.
"""
import argparse
import csv
import json
import os
import random
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from . import service
from .db import connect, init_schema
from .gate_controller import GateController, InProcessLink
from .seed import seed_demo

PEPPER = "simulator-pepper"
START = datetime(2026, 1, 5, 7, 30, 0)


@dataclass
class SimParams:
    seed: int = 42
    trials: int = 100
    reader_loop_ms: float = 40.0      # one read attempt
    jitter_ms: float = 16.0           # uniform extra time per attempt
    max_attempts: int = 3
    server_rtt_mean_ms: float = 120.0
    server_rtt_sd_ms: float = 30.0
    local_decision_ms: float = 10.0
    uhf_range_m: float = 10.0
    hf_range_m: float = 0.05
    gap_s: int = 10                   # seconds between vehicles
    # mix of tags presented: valid, unregistered, expired, revoked, blacklisted
    mix: tuple = (0.60, 0.10, 0.10, 0.10, 0.10)


@dataclass
class Scenario:
    name: str
    reader: str            # UHF | HF
    distance_m: float
    interference: float    # extra probability that any single read attempt is lost
    online: bool
    power: str             # mains | ups | none


SCENARIOS = [
    Scenario("UHF 1.0 m, online", "UHF", 1.0, 0.0, True, "mains"),
    Scenario("UHF 3.7 m, online", "UHF", 3.7, 0.0, True, "mains"),
    Scenario("UHF 3.7 m, server offline", "UHF", 3.7, 0.0, False, "mains"),
    Scenario("UHF 6.0 m, online", "UHF", 6.0, 0.0, True, "mains"),
    Scenario("UHF 8.0 m, online", "UHF", 8.0, 0.0, True, "mains"),
    Scenario("UHF 3.7 m, 20% interference, online", "UHF", 3.7, 0.2, True, "mains"),
    Scenario("UHF 3.7 m, 20% interference, offline", "UHF", 3.7, 0.2, False, "mains"),
    Scenario("UHF 3.7 m, UPS power, online", "UHF", 3.7, 0.0, True, "ups"),
    Scenario("UHF 3.7 m, UPS power, offline", "UHF", 3.7, 0.0, False, "ups"),
    Scenario("UHF 3.7 m, no power", "UHF", 3.7, 0.0, True, "none"),
    Scenario("HF 0.05 m, online", "HF", 0.05, 0.0, True, "mains"),
    Scenario("HF 1.0 m, online", "HF", 1.0, 0.0, True, "mains"),
]

TARGETS = {"identification_s": 1.0, "read_accuracy_pct": 98.0, "processing_s": 3.0,
           "availability_pct": 99.0, "unrecorded": 0}


def read_probability(sc, params):
    """Per-attempt read probability: 1-(d/range)^4 inside range, 0 outside, then interference."""
    rng_m = params.uhf_range_m if sc.reader == "UHF" else params.hf_range_m
    p = max(0.0, 1.0 - (sc.distance_m / rng_m) ** 4)
    return p * (1.0 - sc.interference)


def run_scenario(sc, params):
    rnd = random.Random(params.seed)
    db = connect(":memory:")
    init_schema(db)
    groups = seed_demo(db, PEPPER, START)
    link = InProcessLink(lambda: db, PEPPER)
    gate = GateController(1, link, PEPPER)
    gate.refresh_whitelist(START)
    link.online = sc.online

    p_read = read_probability(sc, params)
    inside, now = set(), START
    ident, proc = [], []
    reads_ok = correct = presented = 0

    for i in range(params.trials):
        now += timedelta(seconds=params.gap_s)
        if sc.power == "none":
            continue                                   # controller is dead: nothing is recorded
        presented += 1
        kind = rnd.choices(["valid", "unregistered", "expired", "revoked", "blacklisted"], params.mix)[0]
        uid = ("UNKNOWN%06d" % rnd.randrange(10**6)) if kind == "unregistered" else rnd.choice(groups[kind])
        direction = "ENTRY"
        if kind == "valid" and uid in inside:
            direction = "EXIT"

        t_ident, ok = 0.0, False
        for _ in range(params.max_attempts):
            t_ident += (params.reader_loop_ms + rnd.uniform(0, params.jitter_ms)) / 1000
            if rnd.random() < p_read:
                ok = True
                break
        if not ok:
            gate.on_no_read(direction, now)
            continue

        res = gate.on_tag_detected(uid, direction, now)
        reads_ok += 1
        ident.append(t_ident)
        if res.path == "SERVER":
            t_decide = max(20.0, rnd.gauss(params.server_rtt_mean_ms, params.server_rtt_sd_ms)) / 1000
        else:
            t_decide = params.local_decision_ms / 1000
        proc.append(t_ident + t_decide)
        if res.decision == ("ADMITTED" if kind == "valid" else "DENIED"):
            correct += 1
        if kind == "valid" and res.decision == "ADMITTED":
            (inside.add if direction == "ENTRY" else inside.discard)(uid)

    pending_before_sync = len(gate.buffer)
    link.online = True                                   # network restored
    gate.sync(now)
    events = db.execute("SELECT COUNT(*) FROM access_event").fetchone()[0]
    lot_count = db.execute("SELECT current_count FROM parking_lot").fetchone()[0]

    def mean(x): return round(statistics.mean(x), 3) if x else None
    def sd(x): return round(statistics.stdev(x), 3) if len(x) > 1 else None

    row = {
        "scenario": sc.name,
        "presentations": presented,
        "read_accuracy_pct": round(100 * reads_ok / presented, 1) if presented else 0.0,
        "identification_mean_s": mean(ident), "identification_sd_s": sd(ident),
        "identification_min_s": round(min(ident), 3) if ident else None,
        "identification_max_s": round(max(ident), 3) if ident else None,
        "processing_mean_s": mean(proc), "processing_sd_s": sd(proc),
        "decision_correct_pct": round(100 * correct / reads_ok, 1) if reads_ok else None,
        "availability_pct": 0.0 if sc.power == "none" else 100.0,
        "unrecorded": params.trials - events if sc.power != "none" else params.trials,
        "buffered_then_synced": pending_before_sync,
        "vehicles_inside_per_lot_count": lot_count,
        "vehicles_inside_per_simulator": len(inside),
    }
    ok_id = row["identification_mean_s"] is not None and row["identification_mean_s"] <= TARGETS["identification_s"]
    ok_pr = row["processing_mean_s"] is not None and row["processing_mean_s"] <= TARGETS["processing_s"]
    row["targets_met"] = bool(ok_id and ok_pr and row["read_accuracy_pct"] >= TARGETS["read_accuracy_pct"]
                              and row["availability_pct"] >= TARGETS["availability_pct"]
                              and row["unrecorded"] == TARGETS["unrecorded"])
    db.close()
    return row


def run_all(params=None):
    params = params or SimParams()
    return [run_scenario(sc, params) for sc in SCENARIOS]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="results", help="folder for results.csv and results.json")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--trials", type=int, default=100)
    a = ap.parse_args()
    params = SimParams(seed=a.seed, trials=a.trials)
    rows = run_all(params)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.out, "results.json"), "w") as f:
        json.dump({"parameters": asdict(params), "targets": TARGETS, "results": rows}, f, indent=2)
    print("%-40s %7s %9s %9s %8s %7s %s" % ("Scenario", "Read%", "Ident(s)", "Proc(s)", "Correct%", "Unrec", "Met"))
    for r in rows:
        f3 = lambda v: "-" if v is None else "%.3f" % v
        print("%-40s %7.1f %9s %9s %8s %7d %s" % (
            r["scenario"], r["read_accuracy_pct"], f3(r["identification_mean_s"]), f3(r["processing_mean_s"]),
            "-" if r["decision_correct_pct"] is None else "%.1f" % r["decision_correct_pct"],
            r["unrecorded"], "yes" if r["targets_met"] else "NO"))
    print("\nWrote %s/results.csv and results.json (seed=%d, trials=%d)" % (a.out, a.seed, a.trials))


if __name__ == "__main__":
    main()
