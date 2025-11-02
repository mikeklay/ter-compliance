# compliance/routes/__init__.py
"""Route blueprints for the compliance application."""
from . import views, engineer, manager, admin, auth

__all__ = ['views', 'engineer', 'manager', 'admin', 'auth']