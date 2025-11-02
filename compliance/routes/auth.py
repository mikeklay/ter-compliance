from flask import Blueprint, request, jsonify, make_response, render_template, redirect, url_for
from compliance.models import db, User
from compliance.auth_utils import make_jwt, current_token_payload

bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.get("/login")
def login_form():
    return render_template("login.html")

@bp.post("/login")
def login():
    # Accept JSON or form
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    pwd   = data.get("password") or ""

    user = User.query.filter_by(email=email, is_active=True).first()
    if not user or not user.check_password(pwd):
        # For browsers, show the form again with a generic error
        if "text/html" in request.headers.get("Accept", "") or request.content_type.startswith("application/x-www-form-urlencoded"):
            return render_template("login.html", error="Invalid email or password"), 401
        return jsonify({"error": "invalid credentials"}), 401

    token = make_jwt(user.id, user.role, user.email)

    # Browser (form) → set cookie and redirect
    if request.content_type and request.content_type.startswith("application/x-www-form-urlencoded"):
        resp = make_response(redirect(request.args.get("next") or url_for("views.home")))
        resp.set_cookie("jwt", token, httponly=True, samesite="Lax")
        return resp

    # JSON clients
    resp = make_response(jsonify({"ok": True, "role": user.role}))
    resp.set_cookie("jwt", token, httponly=True, samesite="Lax")
    return resp

@bp.get("/logout")
def logout_get():
    # convenient for browsers
    resp = make_response(redirect(url_for("auth.login_form")))
    resp.set_cookie("jwt", "", expires=0)
    return resp

@bp.post("/logout")
def logout_post():
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie("jwt", "", expires=0)
    return resp

@bp.get("/whoami")
def whoami():
    return jsonify(current_token_payload() or {"anon": True})
