"""Verified backup and disaster-recovery controls for Malenge Farmers CRM.

Recovery bundles deliberately include the database plus protected evidence stores.
They are designed to be copied off-host after creation; local bundles alone are not
an off-site backup strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import click
import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import text as sql_text


_core = sys.modules.get("app")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")

bp = Blueprint("backuprecovery", __name__)

_BUNDLE_NAME_RE = re.compile(r"^malenge_recovery_\d{8}_\d{6}_[0-9a-f]{8}\.zip$")
_MANIFEST_NAME = "manifest.json"
_ARCHIVE_VERSION = 1


class RecoveryError(RuntimeError):
    """Controlled recovery-operation failure safe to show to an administrator."""


def _utc_now():
    return datetime.now(timezone.utc)


def recovery_bundle_directory():
    raw = os.getenv(
        "RECOVERY_BUNDLE_DIR",
        str(Path(_core.app.instance_path) / "recovery_bundles"),
    )
    path = Path(raw).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def recovery_retention_limit():
    try:
        configured = int(os.getenv("RECOVERY_BUNDLE_RETENTION", "7"))
    except ValueError:
        configured = 7
    return max(1, min(configured, 90))


def _safe_bundle_path(bundle_name):
    name = Path(bundle_name or "").name
    if name != bundle_name or not _BUNDLE_NAME_RE.fullmatch(name):
        abort(404)
    directory = recovery_bundle_directory()
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        abort(404)
    return path


def _hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _hash_zip_member(archive, member_name):
    digest = hashlib.sha256()
    size = 0
    with archive.open(member_name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _schema_revision():
    try:
        row = _core.db.session.execute(sql_text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        return row[0] if row else None
    except Exception:
        try:
            _core.db.session.rollback()
        except Exception:
            pass
        return None


def _database_backend():
    return _core.db.engine.url.get_backend_name()


def _sqlite_snapshot(target):
    database_path = _core.sqlite_database_path()
    if not database_path or not database_path.exists():
        raise RecoveryError("The SQLite database file could not be found.")

    source = sqlite3.connect(str(database_path))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _postgres_snapshot(target):
    executable = shutil.which("pg_dump")
    if not executable:
        raise RecoveryError(
            "PostgreSQL recovery bundle creation requires pg_dump on the application host. "
            "Use the database provider snapshot system if pg_dump is not installed."
        )

    url = _core.db.engine.url
    environment = os.environ.copy()
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port or 5432),
        "PGDATABASE": url.database,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
    }
    for key, value in values.items():
        if value is not None:
            environment[key] = str(value)

    query = dict(url.query or {})
    if query.get("sslmode"):
        environment["PGSSLMODE"] = str(query["sslmode"])

    command = [
        executable,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(target),
    ]
    try:
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError("PostgreSQL backup could not be completed by pg_dump.") from None

    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise RecoveryError("PostgreSQL backup could not be completed by pg_dump.")


def _create_database_snapshot(temp_directory):
    backend = _database_backend()
    if backend == "sqlite":
        target = temp_directory / "database.sqlite3"
        _sqlite_snapshot(target)
        return target, "sqlite"
    if backend == "postgresql":
        target = temp_directory / "database.pgdump"
        _postgres_snapshot(target)
        return target, "postgresql-custom"
    raise RecoveryError(f"Recovery bundle creation does not support the configured database backend: {backend}.")


def _evidence_sources():
    sources = []
    seen = set()

    accountability = Path(_core.ACCOUNTABILITY_UPLOAD_DIR).expanduser().resolve()
    sources.append(("accountability", accountability))
    seen.add(accountability)

    try:
        phase7 = importlib.import_module("phase7")
        documents = Path(phase7.DOCUMENT_UPLOAD_DIR).expanduser().resolve()
        if documents not in seen:
            sources.append(("documents", documents))
            seen.add(documents)
    except Exception:
        pass

    return sources


def _add_file(archive, source_path, archive_name, manifest_files):
    digest, size = _hash_file(source_path)
    archive.write(source_path, archive_name)
    manifest_files.append({
        "path": archive_name,
        "sha256": digest,
        "size": size,
    })


def _add_directory(archive, label, directory, manifest_files):
    count = 0
    total_size = 0
    if not directory.exists():
        return {"label": label, "file_count": 0, "bytes": 0, "missing": True}
    if not directory.is_dir():
        raise RecoveryError(f"The configured {label} evidence storage is not a directory.")

    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative = path.relative_to(directory).as_posix()
        archive_name = f"evidence/{label}/{relative}"
        _add_file(archive, path, archive_name, manifest_files)
        count += 1
        total_size += path.stat().st_size

    return {"label": label, "file_count": count, "bytes": total_size, "missing": False}


def _system_settings_file():
    try:
        path = Path(_core.system_settings_path()).resolve()
        return path if path.exists() and path.is_file() else None
    except Exception:
        return None


def _new_bundle_name():
    stamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    token = os.urandom(4).hex()
    return f"malenge_recovery_{stamp}_{token}.zip"


def prune_recovery_bundles():
    bundles = sorted(
        recovery_bundle_directory().glob("malenge_recovery_*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for path in bundles[recovery_retention_limit():]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            _core.app.logger.warning("Could not prune recovery bundle %s", path.name)
    return removed


def create_recovery_bundle():
    """Create a database + evidence recovery archive with per-file SHA-256 hashes."""
    directory = recovery_bundle_directory()
    final_path = directory / _new_bundle_name()
    temporary_path = final_path.with_suffix(".tmp")

    if temporary_path.exists():
        temporary_path.unlink()

    manifest_files = []
    evidence_summary = []

    try:
        with tempfile.TemporaryDirectory(prefix="malenge_recovery_") as temp:
            temp_directory = Path(temp)
            database_file, database_format = _create_database_snapshot(temp_directory)

            with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
                database_archive_name = f"database/{database_file.name}"
                _add_file(archive, database_file, database_archive_name, manifest_files)

                for label, evidence_directory in _evidence_sources():
                    evidence_summary.append(
                        _add_directory(archive, label, evidence_directory, manifest_files)
                    )

                settings_file = _system_settings_file()
                settings_included = False
                if settings_file:
                    _add_file(
                        archive,
                        settings_file,
                        "configuration/system_settings.json",
                        manifest_files,
                    )
                    settings_included = True

                manifest = {
                    "archive_version": _ARCHIVE_VERSION,
                    "application": "Malenge Farmers CRM",
                    "created_at": _utc_now().isoformat(),
                    "database_backend": _database_backend(),
                    "database_format": database_format,
                    "database_archive_path": database_archive_name,
                    "schema_revision": _schema_revision(),
                    "evidence": evidence_summary,
                    "system_settings_included": settings_included,
                    "file_count": len(manifest_files),
                    "files": manifest_files,
                }
                archive.writestr(
                    _MANIFEST_NAME,
                    json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                )

        temporary_path.replace(final_path)
        prune_recovery_bundles()
        return final_path
    except RecoveryError:
        if temporary_path.exists():
            temporary_path.unlink()
        raise
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        _core.app.logger.exception("Unexpected recovery bundle creation failure")
        raise RecoveryError("The recovery bundle could not be created safely.") from None


def _read_manifest(path):
    try:
        with ZipFile(path, "r") as archive:
            raw = archive.read(_MANIFEST_NAME)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (BadZipFile, KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def verify_recovery_bundle(path):
    """Verify archive structure and every file hash recorded by the manifest."""
    path = Path(path)
    try:
        with ZipFile(path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                return False, "Archive contains duplicate file entries."
            if _MANIFEST_NAME not in names:
                return False, "Archive manifest is missing."

            manifest = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
            if manifest.get("archive_version") != _ARCHIVE_VERSION:
                return False, "Archive version is not supported."
            database_path = manifest.get("database_archive_path")
            files = manifest.get("files")
            if not database_path or not isinstance(files, list):
                return False, "Archive manifest is incomplete."
            if database_path not in names:
                return False, "Database snapshot is missing."

            expected_paths = set()
            for entry in files:
                if not isinstance(entry, dict):
                    return False, "Archive manifest contains an invalid file record."
                member = entry.get("path")
                expected_hash = entry.get("sha256")
                expected_size = entry.get("size")
                if not member or member in expected_paths or member not in names:
                    return False, "Archive contents do not match the manifest."
                expected_paths.add(member)
                actual_hash, actual_size = _hash_zip_member(archive, member)
                if actual_hash != expected_hash or actual_size != expected_size:
                    return False, "Archive integrity verification failed."

            if database_path not in expected_paths:
                return False, "Database snapshot is not protected by the manifest."

            return True, manifest
    except (BadZipFile, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return False, "Archive integrity verification failed."


def list_recovery_bundles():
    bundles = []
    for path in sorted(
        recovery_bundle_directory().glob("malenge_recovery_*.zip"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        manifest = _read_manifest(path) or {}
        stat = path.stat()
        evidence = manifest.get("evidence") if isinstance(manifest.get("evidence"), list) else []
        bundles.append({
            "name": path.name,
            "created_at": datetime.fromtimestamp(stat.st_mtime),
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "database_backend": manifest.get("database_backend", "Unknown"),
            "schema_revision": manifest.get("schema_revision") or "Unknown",
            "file_count": manifest.get("file_count", 0),
            "evidence_file_count": sum(int(item.get("file_count", 0)) for item in evidence if isinstance(item, dict)),
            "manifest_ok": bool(manifest),
        })
    return bundles


def recovery_capabilities():
    backend = _database_backend()
    pg_dump_available = bool(shutil.which("pg_dump")) if backend == "postgresql" else None
    return {
        "database_backend": backend,
        "can_create_complete_bundle": backend == "sqlite" or (backend == "postgresql" and pg_dump_available),
        "pg_dump_available": pg_dump_available,
        "retention": recovery_retention_limit(),
        "bundle_directory_persistent": bool(os.getenv("RECOVERY_BUNDLE_DIR")),
        "evidence_sources": [label for label, _path in _evidence_sources()],
    }


@bp.get("/admin/recovery")
@_core.roles_required("Admin")
def admin_recovery():
    return render_template(
        "admin_recovery.html",
        bundles=list_recovery_bundles(),
        capabilities=recovery_capabilities(),
        notice=request.args.get("notice", "").strip(),
    )


@bp.post("/admin/recovery/create")
@_core.roles_required("Admin")
def admin_recovery_create():
    try:
        bundle = create_recovery_bundle()
    except RecoveryError as exc:
        _core.app.logger.warning("Recovery bundle creation failed error_type=%s", type(exc).__name__)
        abort(503, description=str(exc))

    _core.add_audit_log(
        "RECOVERY_BUNDLE_CREATE",
        "System",
        details=f"Created complete recovery bundle {bundle.name}.",
    )
    _core.db.session.commit()
    return redirect(url_for("backuprecovery.admin_recovery", notice="Recovery bundle created."))


@bp.get("/admin/recovery/<path:bundle_name>/download")
@_core.roles_required("Admin")
def admin_recovery_download(bundle_name):
    path = _safe_bundle_path(bundle_name)
    _core.add_audit_log(
        "RECOVERY_BUNDLE_DOWNLOAD",
        "System",
        details=f"Downloaded recovery bundle {path.name}.",
    )
    _core.db.session.commit()
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.post("/admin/recovery/<path:bundle_name>/verify")
@_core.roles_required("Admin")
def admin_recovery_verify(bundle_name):
    path = _safe_bundle_path(bundle_name)
    verified, _details = verify_recovery_bundle(path)
    _core.add_audit_log(
        "RECOVERY_BUNDLE_VERIFY" if verified else "RECOVERY_BUNDLE_VERIFY_FAILED",
        "System",
        details=f"Integrity verification {'passed' if verified else 'failed'} for recovery bundle {path.name}.",
    )
    _core.db.session.commit()
    if not verified:
        abort(409, description="The recovery bundle failed integrity verification and must not be used for recovery.")
    return redirect(url_for("backuprecovery.admin_recovery", notice="Recovery bundle integrity verified."))


@bp.post("/admin/recovery/<path:bundle_name>/delete")
@_core.roles_required("Admin")
def admin_recovery_delete(bundle_name):
    if request.form.get("confirmation", "").strip().upper() != "DELETE":
        abort(400, description="Type DELETE to remove a stored recovery bundle.")
    path = _safe_bundle_path(bundle_name)
    name = path.name
    path.unlink()
    _core.add_audit_log(
        "RECOVERY_BUNDLE_DELETE",
        "System",
        details=f"Deleted local recovery bundle {name}.",
    )
    _core.db.session.commit()
    return redirect(url_for("backuprecovery.admin_recovery", notice="Recovery bundle deleted."))


def _cli_create_bundle():
    """Create a complete bundle for cron/scheduled backup jobs."""
    try:
        bundle = create_recovery_bundle()
    except RecoveryError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(bundle.name)


def _cli_verify_bundle(bundle_name):
    path = recovery_bundle_directory() / Path(bundle_name).name
    if not path.is_file() or not _BUNDLE_NAME_RE.fullmatch(path.name):
        raise click.ClickException("Recovery bundle was not found.")
    verified, details = verify_recovery_bundle(path)
    if not verified:
        raise click.ClickException(str(details))
    click.echo(f"verified: {path.name}")


def register_backup_recovery(app):
    """Register recovery UI and automation commands exactly once."""
    if "backuprecovery" not in app.blueprints:
        app.register_blueprint(bp)

    if "create-recovery-bundle" not in app.cli.commands:
        app.cli.add_command(click.command("create-recovery-bundle")(_cli_create_bundle))

    if "verify-recovery-bundle" not in app.cli.commands:
        command = click.command("verify-recovery-bundle")(_cli_verify_bundle)
        command = click.argument("bundle_name")(command)
        app.cli.add_command(command)
