import os, time, jwt
from functools import wraps
from flask import request, jsonify, g

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")  # set a real secret in prod
JWT_ALG = "HS256"
JWT_TTL = 60 * 60 * 8  # 8 hours

def make_jwt(uid: int, role: str, email: str) -> str:
    now = int(time.time())
    payload = {
        "uid": uid,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + JWT_TTL,
        "iss": "compliance",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def parse_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG], issuer="compliance")
    except Exception:
        return None

def current_token_payload() -> dict | None:
    # 1) Authorization: Bearer <token>
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1].strip()
        return parse_jwt(token)
    # 2) Cookie "jwt"
    cookie_token = request.cookies.get("jwt")
    if cookie_token:
        return parse_jwt(cookie_token)
    return None

def require_roles(*roles):
    """Use as @require_roles('admin', 'manager')"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            payload = current_token_payload()
            if not payload:
                return jsonify({"error": "auth required"}), 401
            if roles and payload.get("role") not in roles:
                return jsonify({"error": "forbidden"}), 403
            g.user_id = payload.get("uid")
            g.role = payload.get("role")
            g.user_email = payload.get("email")
            return fn(*args, **kwargs)
        return wrapper
    return deco
