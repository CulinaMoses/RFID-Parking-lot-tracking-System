# RFID Smart Automobile Parking Lots Tracking System (University of Ibadan)

CSC 476 / Research Methods in Computer Science group project: software implementation.

A working reference implementation of the system designed in Chapters 3 and 4 of the project report:
a Flask + SQLite server with a web interface, the gate-controller (edge) logic with offline
operation, and a tag-read simulator that reproduces the 12 evaluation scenarios.

**Scope.** This repository is the *software* side. There is no microcontroller firmware and no
physical reader here: the reader is simulated, and the gate-controller logic is written in Python
so it can be tested. See [Limitations](#limitations).

## Quick start

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m app.seed                 # creates instance/parking.db with demo users and vehicles
python run.py                      # http://127.0.0.1:5000
```

Demo accounts (password `ChangeMe!2026`, change them): `admin` (ADMIN), `gate1` (SECURITY), `ict1` (ICT).
Demo tag UIDs are listed in `instance/demo_tags.txt` (`valid`, `expired`, `revoked`, `blacklisted`).

Try this in the browser as `gate1`: **Gate console** -> present a `valid` UID (green, barrier lifts) ->
a `revoked` UID (red, alert raised) -> *Simulate server outage* -> present another `valid` UID (still
admitted from the local whitelist, event buffered) -> *Restore connection* -> *Sync now*.

## Tests and simulator

```bash
python -m unittest discover -v     # 26 tests (T01-T18 functional + simulator checks)
python -m app.simulator --out results   # 12 scenarios, seed 42 -> results/results.csv and .json
```

## How it maps to the design

| Report item | Where |
|---|---|
| ERD, nine entities (Fig. 4.3) | `app/schema.sql` (plus an `audit_log` table, needed for FR11) |
| Gate access algorithm, debounce, local whitelist, offline buffer, sync (4.4.4) | `app/gate_controller.py`, `app/service.py` (`process_event`, `evaluate`, `sync_events`) |
| Registration, visitor passes, occupancy, alerts, override, reports (FR1-FR10) | `app/service.py`, `app/routes.py` |
| Roles, hashed passwords, hashed tag UIDs, audit log (FR11, NFR4/5) | `app/security.py`, `audit_log` table |
| Web interface (gate console, dashboard, vehicles, visitors, alerts, reports, users) | `app/static/` |
| Simulated evaluation (4.5) | `app/simulator.py` |

### Access decision order
Revoked -> suspended -> expired tag -> blacklisted vehicle -> suspended vehicle -> admitted. A tag
that is not registered is checked against visitor passes (valid window, not cancelled); otherwise it is
denied as unregistered. Every denial raises an alert. An entry read for a vehicle already recorded
inside raises `DUPLICATE_READ` (the vehicle is admitted but not counted twice); an exit with no entry on
record raises `UNMATCHED_EXIT`. Going over capacity raises `LOT_FULL` but does not block entry.

### Offline behaviour
While the server is unreachable the controller decides from its whitelist of hashed UIDs and buffers
each event with a unique reference. On reconnection the events are replayed oldest first; replaying the
same event twice has no effect. If a tag was revoked while the gate was offline, the sync records the
admission and raises `OFFLINE_MISMATCH`.

## REST API (all under `/api`, JSON)

| Area | Endpoints | Who |
|---|---|---|
| Session | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | all |
| Vehicles and tags | `POST/GET /vehicles`, `PATCH /vehicles/<id>`, `POST /vehicles/<id>/tags`, `PATCH /tags/<id>` | ADMIN (GET: + SECURITY) |
| Visitors | `POST/GET /visitor-passes`, `POST /visitor-passes/<id>/cancel` | SECURITY, ADMIN |
| Monitoring | `GET /dashboard`, `/gates`, `/events`, `/alerts`; `POST /alerts/<id>/ack`; `GET /reports/events.csv` | by role |
| Override | `POST /gate/override` | SECURITY, ADMIN |
| Users and audit | `GET/POST /users`, `PATCH /users/<id>`, `GET /audit` | ICT, ADMIN |
| Gate controller | `POST /gate/event`, `POST /gate/sync`, `GET /gate/whitelist` (header `X-Gate-Key`) | gate devices |
| Browser demo | `POST /sim/read`, `/sim/network`, `/sim/sync`, `GET /sim/state` | SECURITY, ADMIN |

## Configuration

Set these environment variables for anything other than a local demo:
`RFID_SECRET_KEY` (session signing), `RFID_PEPPER` (key for hashing tag UIDs; changing it invalidates
all stored tags), `RFID_GATE_KEY` (gate API key), `RFID_HTTPS=1` (marks the session cookie Secure).

## Simulator notes

The simulator drives the real controller and server code against an in-memory database. What is
**modelled** (parameters in `SimParams`): the read probability per attempt, `1 - (distance/range)^4`
(UHF range 10 m, HF range 0.05 m), reduced by any interference; up to 3 attempts of about 40 ms plus up
to 16 ms jitter; server round trip about 120 ms (SD 30 ms); local decision 10 ms. Identification and
processing **times are therefore modelled values, not hardware measurements**. What is **real**: every
decision, alert, occupancy count, offline buffer and sync, and the "no unrecorded events" check, which
counts rows in the database after reconnection. Results are deterministic for a given seed.

## Limitations

- No device firmware or real reader; the reader and network delays are simulated.
- The app serves plain HTTP. Encrypted transport (TLS) must be provided by a reverse proxy (for example
  nginx) in deployment; it is not implemented in the application.
- Gate devices share one API key; there is no per-device credential, rate limiting or account lockout.
- SQLite and a single process suit a demonstration, not a multi-gate production deployment. The
  in-process gate controllers used by the browser demo are not shared across processes.
- The web interface was written without an automated browser test; the API behind it is covered by the tests.
- Times are stored in UTC; the interface shows them in the browser's local time.
