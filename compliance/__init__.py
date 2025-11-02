# compliance/__init__.py
from __future__ import annotations

import os
import click
from flask import Flask, g, request, redirect, url_for
from flasgger import Swagger
from flask_migrate import Migrate

from .config import load_config
from .models import db
from .routes import views, engineer, manager, admin, auth
from .seed import seed_data
from .auth_utils import current_token_payload


def create_app(config_override: dict | None = None):
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- Config ---
    cfg = load_config() or {}

    # Prefer DATABASE_URL if present (e.g., for RDS/MySQL):
    # mysql+pymysql://username:password@host:3306/dbname
    db_url_env = os.getenv("DATABASE_URL")
    if db_url_env:
        cfg["SQLALCHEMY_DATABASE_URI"] = db_url_env

    cfg.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-change-me"))
    cfg.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    if config_override:
        cfg.update(config_override)

    app.config.from_mapping(cfg)

    # --- Extensions ---
    db.init_app(app)
    Migrate(app, db)  # enables: flask db init/migrate/upgrade

    Swagger(app, config={
        "headers": [],
        "specs": [{
            "endpoint": "apispec_1",
            "route": "/apispec_1.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs",
    })

    # --- Blueprints ---
    app.register_blueprint(auth.bp)                    # /auth/*
    app.register_blueprint(views.bp)                   # /
    app.register_blueprint(engineer.bp, url_prefix="/engineer")
    app.register_blueprint(manager.bp,  url_prefix="/manager")
    app.register_blueprint(admin.bp,    url_prefix="/admin")

    # --- Request hook: attach user info + gentle redirect to login for HTML pages ---
    @app.before_request
    def attach_user():
        payload = current_token_payload()
        if payload:
            g.user_id = payload.get("uid")
            g.role = payload.get("role")
            g.user_email = payload.get("email")
        else:
            g.user_id = None
            g.role = None
            g.user_email = None

        # If not authenticated and requesting HTML, send to login (allow auth/static/docs)
        path = request.path or ""
        wants_html = "text/html" in (request.headers.get("Accept", "") or "")
        if (g.user_id is None) and request.method == "GET" and wants_html:
            if not (
                path.startswith("/auth")
                or path.startswith("/static")
                or path.startswith("/apidocs")
                or path.startswith("/apispec_1.json")
            ):
                return redirect(url_for("auth.login_form"))

    # --- Template globals for navbar/visibility toggles ---
    @app.context_processor
    def inject_session_role():
        return {
            "session_role": g.get("role") or "engineer",
            "session_email": g.get("user_email"),
        }

    # --- CLI helpers (handy locally; migrations are preferred for prod) ---
    @app.cli.command("init-db")
    def init_db_cmd():
        """Create all tables quickly (use migrations for schema changes)."""
        with app.app_context():
            db.create_all()
        click.echo("Database initialized.")

    @app.cli.command("seed")
    def seed_cmd():
        """Load seed data (users, labs, courses, etc.)."""
        with app.app_context():
            seed_data()
        click.echo("Seed data inserted.")

    return app
