"""REST API. All endpoints are under /api."""
from flask import Blueprint, Response, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash

from . import service
from .db import get_db
from .gate_controller import GateController, InProcessLink
from .security import gate_key_required, login_required

bp = Blueprint("api", __name__, url_prefix="/api")


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _need(data, *names):
    missing = [n for n in names if data.get(n) in (None, "")]
    if missing:
        raise ValueError("Missing field(s): " + ", ".join(missing))
    return [data[n] for n in names]


def _int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)


# ------------------------------------------------------------- session ----
@bp.get("/health")
def health():
    return jsonify(status="ok", time=service.iso(service.utcnow()))


@bp.post("/auth/login")
def login():
    d = _body()
    username, password = str(d.get("username", "")), str(d.get("password", ""))
    db = get_db()
    user = db.execute("SELECT * FROM user_account WHERE username=? AND active=1", (username,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        service.audit(db, username[:32], "LOGIN_FAILED", request.remote_addr or "")
        return jsonify(error="Invalid username or password"), 401
    session.clear()
    session["user_id"] = user["user_id"]
    service.audit(db, username, "LOGIN", "")
    return jsonify(username=user["username"], role=user["role"])


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/auth/me")
@login_required()
def me():
    return jsonify(username=g.user["username"], role=g.user["role"])


# ------------------------------------------------- registration (admin) ----
@bp.post("/vehicles")
@login_required("ADMIN")
def add_vehicle():
    d = _body()
    plate, = _need(d, "plate")
    owner = d.get("owner") or {}
    res = service.create_vehicle(get_db(), owner, plate, d.get("make_model", ""), d.get("colour", ""))
    service.audit(get_db(), g.user["username"], "VEHICLE_REGISTERED", "plate=" + plate.upper())
    return jsonify(res), 201


@bp.get("/vehicles")
@login_required("SECURITY")
def list_vehicles():
    db = get_db()
    rows = [dict(r) for r in db.execute(
        "SELECT v.vehicle_id, v.plate, v.make_model, v.colour, v.status, o.full_name, o.category, o.department "
        "FROM vehicle v JOIN owner o ON o.owner_id=v.owner_id ORDER BY v.vehicle_id DESC LIMIT 500")]
    tags = {}
    for t in db.execute("SELECT tag_id, vehicle_id, state, expires_at FROM rfid_tag ORDER BY tag_id"):
        tags.setdefault(t["vehicle_id"], []).append(dict(t))
    for r in rows:
        r["tags"] = tags.get(r["vehicle_id"], [])
    return jsonify(rows)


@bp.patch("/vehicles/<int:vehicle_id>")
@login_required("ADMIN")
def patch_vehicle(vehicle_id):
    status, = _need(_body(), "status")
    service.set_vehicle_status(get_db(), vehicle_id, status)
    service.audit(get_db(), g.user["username"], "VEHICLE_STATUS", "vehicle=%d status=%s" % (vehicle_id, status.upper()))
    return jsonify(ok=True)


@bp.post("/vehicles/<int:vehicle_id>/tags")
@login_required("ADMIN")
def add_tag(vehicle_id):
    d = _body()
    uid, = _need(d, "uid")
    tid = service.issue_tag(get_db(), current_app.config["PEPPER"], vehicle_id, uid, d.get("expires_at"))
    service.audit(get_db(), g.user["username"], "TAG_ISSUED", "vehicle=%d tag=%d" % (vehicle_id, tid))
    return jsonify(tag_id=tid), 201


@bp.patch("/tags/<int:tag_id>")
@login_required("ADMIN")
def patch_tag(tag_id):
    state, = _need(_body(), "state")
    service.set_tag_state(get_db(), tag_id, state)
    service.audit(get_db(), g.user["username"], "TAG_STATE", "tag=%d state=%s" % (tag_id, state.upper()))
    return jsonify(ok=True)


# ----------------------------------------------------------- visitors ----
@bp.post("/visitor-passes")
@login_required("SECURITY")
def add_pass():
    d = _body()
    name, plate, uid, vf, vu = _need(d, "visitor_name", "plate", "uid", "valid_from", "valid_until")
    pid = service.issue_visitor_pass(get_db(), current_app.config["PEPPER"], name, plate, d.get("host", ""),
                                     uid, vf, vu, g.user["username"])
    service.audit(get_db(), g.user["username"], "VISITOR_PASS_ISSUED", "pass=%d plate=%s" % (pid, plate.upper()))
    return jsonify(pass_id=pid), 201


@bp.get("/visitor-passes")
@login_required("SECURITY")
def list_passes():
    rows = get_db().execute(
        "SELECT pass_id, visitor_name, plate, host, valid_from, valid_until, state, created_by "
        "FROM visitor_pass ORDER BY pass_id DESC LIMIT 200").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/visitor-passes/<int:pass_id>/cancel")
@login_required("SECURITY")
def cancel_pass(pass_id):
    service.cancel_visitor_pass(get_db(), pass_id)
    service.audit(get_db(), g.user["username"], "VISITOR_PASS_CANCELLED", "pass=%d" % pass_id)
    return jsonify(ok=True)


# ----------------------------------------- monitoring, alerts, reports ----
@bp.get("/dashboard")
@login_required()
def dashboard():
    return jsonify(service.dashboard(get_db(), service.utcnow()))


@bp.get("/gates")
@login_required()
def gates():
    rows = get_db().execute("SELECT g.gate_id, g.name, p.name AS lot FROM gate g "
                            "JOIN parking_lot p ON p.lot_id=g.lot_id ORDER BY g.gate_id").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/events")
@login_required("SECURITY")
def events():
    return jsonify(service.list_events(
        get_db(), limit=min(_int(request.args.get("limit", 50), "limit"), 500),
        decision=request.args.get("decision"), start=request.args.get("start"), end=request.args.get("end")))


@bp.get("/reports/events.csv")
@login_required("SECURITY")
def report_csv():
    body = service.events_csv(get_db(), request.args.get("start"), request.args.get("end"))
    service.audit(get_db(), g.user["username"], "REPORT_EXPORTED", "events.csv")
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=access_events.csv"})


@bp.get("/alerts")
@login_required()
def alerts():
    status = (request.args.get("status") or "").upper()
    sql = "SELECT alert_id, event_id, type, message, created_at, status, acknowledged_by FROM alert "
    args = []
    if status in ("OPEN", "ACKNOWLEDGED"):
        sql += "WHERE status=? "
        args.append(status)
    rows = get_db().execute(sql + "ORDER BY alert_id DESC LIMIT 200", args).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/alerts/<int:alert_id>/ack")
@login_required("SECURITY")
def ack_alert(alert_id):
    service.acknowledge_alert(get_db(), alert_id, g.user["username"])
    service.audit(get_db(), g.user["username"], "ALERT_ACKNOWLEDGED", "alert=%d" % alert_id)
    return jsonify(ok=True)


@bp.post("/gate/override")
@login_required("SECURITY")
def override():
    d = _body()
    gate_id, direction, note = _need(d, "gate_id", "direction", "note")
    res = service.manual_override(get_db(), _int(gate_id, "gate_id"), direction, note,
                                  g.user["username"], service.iso(service.utcnow()))
    return jsonify(res), 201


# ------------------------------------------------- users and audit ----
@bp.get("/users")
@login_required("ICT")
def users():
    rows = get_db().execute("SELECT user_id, username, role, active, created_at FROM user_account "
                            "ORDER BY user_id").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/users")
@login_required("ICT")
def add_user():
    username, password, role = _need(_body(), "username", "password", "role")
    uid = service.create_user(get_db(), username, password, role)
    service.audit(get_db(), g.user["username"], "USER_CREATED", "username=%s role=%s" % (username, role.upper()))
    return jsonify(user_id=uid), 201


@bp.patch("/users/<int:user_id>")
@login_required("ICT")
def patch_user(user_id):
    active = 1 if _body().get("active") else 0
    if user_id == g.user["user_id"] and not active:
        raise ValueError("You cannot deactivate your own account")
    with get_db() as db:
        cur = db.execute("UPDATE user_account SET active=? WHERE user_id=?", (active, user_id))
    if cur.rowcount == 0:
        raise ValueError("User not found")
    service.audit(get_db(), g.user["username"], "USER_ACTIVE", "user=%d active=%d" % (user_id, active))
    return jsonify(ok=True)


@bp.get("/audit")
@login_required("ICT")
def audit_log():
    rows = get_db().execute("SELECT audit_id, username, action, detail, at FROM audit_log "
                            "ORDER BY audit_id DESC LIMIT 300").fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------- gate-controller API (API key) ----
@bp.post("/gate/event")
@gate_key_required
def gate_event():
    d = _body()
    gate_id, direction, ts = _need(d, "gate_id", "direction", "ts")
    return jsonify(service.process_event(
        get_db(), current_app.config["PEPPER"], uid=d.get("uid"), gate_id=_int(gate_id, "gate_id"),
        direction=direction, ts=ts, edge_decision=d.get("edge_decision"), source="ONLINE",
        client_ref=d.get("ref")))


@bp.post("/gate/sync")
@gate_key_required
def gate_sync():
    events_in = _body().get("events")
    if not isinstance(events_in, list):
        raise ValueError("events must be a list")
    return jsonify(service.sync_events(get_db(), current_app.config["PEPPER"], events_in))


@bp.get("/gate/whitelist")
@gate_key_required
def gate_whitelist():
    return jsonify(service.whitelist(get_db(), service.iso(service.utcnow())))


# -------------------------------- in-browser gate demo (simulated reader) ----
def _controller(gate_id):
    ctrls = current_app.extensions["controllers"]
    if gate_id not in ctrls:
        link = InProcessLink(get_db, current_app.config["PEPPER"])
        ctrl = GateController(gate_id, link, current_app.config["PEPPER"])
        ctrl.refresh_whitelist(service.utcnow())
        ctrls[gate_id] = ctrl
    return ctrls[gate_id]


def _gate_state(ctrl):
    return {"gate_id": ctrl.gate_id, "mode": ctrl.mode, "pending": len(ctrl.buffer),
            "whitelist_size": len(ctrl.whitelist)}


@bp.post("/sim/read")
@login_required("SECURITY")
def sim_read():
    d = _body()
    gate_id, direction = _need(d, "gate_id", "direction")
    ctrl = _controller(_int(gate_id, "gate_id"))
    now = service.utcnow()
    if ctrl.mode == "ONLINE":
        ctrl.refresh_whitelist(now)   # demo convenience: a real gate refreshes on a timer
    if d.get("uid"):
        res = ctrl.on_tag_detected(d["uid"], direction.upper(), now)
    else:
        res = ctrl.on_no_read(direction.upper(), now)
    return jsonify({**res.__dict__, "gate": _gate_state(ctrl)})


@bp.post("/sim/network")
@login_required("SECURITY")
def sim_network():
    d = _body()
    gate_id, = _need(d, "gate_id")
    ctrl = _controller(_int(gate_id, "gate_id"))
    ctrl.link.online = bool(d.get("online"))
    return jsonify(_gate_state(ctrl))


@bp.post("/sim/sync")
@login_required("SECURITY")
def sim_sync():
    gate_id, = _need(_body(), "gate_id")
    ctrl = _controller(_int(gate_id, "gate_id"))
    return jsonify({**ctrl.sync(service.utcnow()), "gate": _gate_state(ctrl)})


@bp.get("/sim/state")
@login_required("SECURITY")
def sim_state():
    gate_id = _int(request.args.get("gate_id", 1), "gate_id")
    return jsonify(_gate_state(_controller(gate_id)))
