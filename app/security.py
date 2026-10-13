"""Hashing, authentication and role-based access control."""
import hmac
import hashlib
import re
from functools import wraps

from flask import current_app, g, jsonify, request, session

from .db import get_db


def normalize_uid(uid):
    uid = re.sub(r"[\s:\-]", "", str(uid or "")).upper()
    if not uid or len(uid) > 64:
        raise ValueError("Tag UID must be 1-64 characters")
    return uid


def hash_uid(uid, pepper):
    """Keyed hash of a tag UID. The plain UID is never stored in the database."""
    return hmac.new(pepper.encode(), normalize_uid(uid).encode(), hashlib.sha256).hexdigest()


def login_required(*roles):
    """Require a logged-in, active user. ADMIN may use every endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return jsonify(error="Authentication required"), 401
            user = get_db().execute(
                "SELECT * FROM user_account WHERE user_id=? AND active=1", (user_id,)
            ).fetchone()
            if user is None:
                session.clear()
                return jsonify(error="Authentication required"), 401
            if roles and user["role"] != "ADMIN" and user["role"] not in roles:
                return jsonify(error="You do not have permission for this action"), 403
            g.user = user
            return fn(*args, **kwargs)
        return wrapper
    return deco


def gate_key_required(fn):
    """Gate controllers authenticate with a shared API key (X-Gate-Key header)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-Gate-Key", "")
        if not hmac.compare_digest(supplied, current_app.config["GATE_API_KEY"]):
            return jsonify(error="Invalid gate key"), 401
        return fn(*args, **kwargs)
    return wrapper
