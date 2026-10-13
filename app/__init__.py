"""RFID Smart Automobile Parking Lots Tracking System (University of Ibadan) - Flask application."""
import os

from flask import Flask, jsonify

from .db import close_db, connect, init_schema


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "parking.db"),
        SECRET_KEY=os.environ.get("RFID_SECRET_KEY", "dev-only-change-me"),
        PEPPER=os.environ.get("RFID_PEPPER", "dev-pepper-change-me"),
        GATE_API_KEY=os.environ.get("RFID_GATE_KEY", "dev-gate-key"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("RFID_HTTPS") == "1",
    )
    if config:
        app.config.update(config)
    os.makedirs(app.instance_path, exist_ok=True)

    conn = connect(app.config["DATABASE"])
    init_schema(conn)
    conn.close()

    app.teardown_appcontext(close_db)
    app.extensions["controllers"] = {}

    from .routes import bp
    app.register_blueprint(bp)

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.errorhandler(ValueError)
    def bad_request(err):
        return jsonify(error=str(err)), 400

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cache-Control"] = "no-store" if resp.mimetype == "application/json" else "no-cache"
        return resp

    return app
