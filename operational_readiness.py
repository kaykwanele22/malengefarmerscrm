"""Deployment liveness and readiness probes for Malenge Farmers CRM.

The liveness probe only proves that the Flask process can answer requests. The
readiness probe verifies dependencies required for normal CRM work without
returning connection strings, filesystem paths, or exception details.
"""

import importlib
import os
import sys

from flask import Blueprint, jsonify
from sqlalchemy import text as sql_text


_core = sys.modules.get("app")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")

bp = Blueprint("opsready", __name__)


def _safe_session_rollback():
    """Best-effort cleanup after a failed database probe."""
    try:
        _core.db.session.rollback()
    except Exception:
        pass


def _database_ready():
    """Return True when the configured database accepts a simple query."""
    try:
        _core.db.session.execute(sql_text("SELECT 1"))
        return True
    except Exception:
        _safe_session_rollback()
        return False


def _evidence_storage_ready():
    """Return True when the protected evidence directory is usable."""
    try:
        path = _core.ACCOUNTABILITY_UPLOAD_DIR
        return bool(path.exists() and path.is_dir() and os.access(path, os.R_OK | os.W_OK))
    except (OSError, TypeError, AttributeError):
        return False


@bp.get("/live")
def liveness_probe():
    """Lightweight process liveness probe; deliberately avoids dependency I/O."""
    return jsonify(status="alive", application="Malenge Farmers CRM"), 200


@bp.get("/ready")
def readiness_probe():
    """Dependency-aware readiness probe suitable for a deployment health check."""
    database_ok = _database_ready()
    evidence_storage_ok = _evidence_storage_ready()
    ready = database_ok and evidence_storage_ok
    payload = {
        "status": "ready" if ready else "unavailable",
        "checks": {
            "database": "ok" if database_ok else "unavailable",
            "evidence_storage": "ok" if evidence_storage_ok else "unavailable",
        },
    }
    response = jsonify(payload)
    if not ready:
        response.headers["Retry-After"] = "5"
    return response, 200 if ready else 503


def register_operational_readiness(app):
    """Register operational controls and leadership command surfaces once."""
    if "opsready" not in app.blueprints:
        app.register_blueprint(bp)

    from backup_recovery import register_backup_recovery
    register_backup_recovery(app)

    from executive_command import register_executive_command
    register_executive_command(app)
