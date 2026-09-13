"""Role-aware access controls for Phase 7 controlled documents.

The document register is cooperative-owned business data, not a system-admin
workspace.  This module narrows the original broad Phase 7 document routes
without changing their public endpoint names, so existing finance/governance
links keep working while document content is filtered by role and context.
"""

import importlib
import sys
from functools import wraps

from flask import abort, redirect, render_template, request, send_file, session, url_for


_core = sys.modules.get("app")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")


SECRETARIAT_ROLES = {
    "Secondary Secretary",
    "Secondary Vice Secretary",
    "Primary Secretary",
    "Primary Vice Secretary",
}

LEADERSHIP_ROLES = {
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Primary Chairperson",
    "Primary Vice Chairperson",
}

TREASURER_ROLES = {
    "Secondary Treasurer",
    "Primary Treasurer",
}

# A document type can legitimately serve more than one workspace.  The
# audiences below intentionally overlap so the same evidence can appear to
# every executive who is authorised to use it, without duplicating the file.
TYPE_AUDIENCES = {
    "Constitution": {"governance"},
    "Cooperative Certificate": {"governance"},
    "Land Document": {"governance", "production"},
    "Contract": {"governance", "finance"},
    "Quotation": {"finance"},
    "Invoice": {"finance"},
    "Receipt": {"finance"},
    "Proof of Payment": {"finance"},
    "Meeting Record": {"governance"},
    "Financial Document": {"finance"},
    "Membership Document": {"membership"},
    "Production Document": {"production"},
    "Joint Operations Document": {"joint", "governance"},
    "General": {"leadership"},
}

# Linked records add context to the document's type.  A linked record never
# expands cooperative scope; it only expands the authorised audience inside
# the same cooperative.
ENTITY_AUDIENCES = {
    "LedgerTransaction": "finance",
    "FinanceReconciliation": "finance",
    "BankReconciliation": "finance",
    "Budget": "finance",
    "Expense": "finance",
    "Payment": "finance",
    "Sale": "finance",
    "Contribution": "finance",
    "PrimaryContributionPayment": "joint",
    "Meeting": "governance",
    "Resolution": "governance",
    "Task": "governance",
    "Membership": "membership",
    "Farmer": "membership",
    "Farm": "production",
    "Crop": "production",
    "Harvest": "production",
    "Equipment": "production",
    "ProductionInput": "production",
    "EquipmentUsage": "production",
    "JointMarketContract": "joint",
    "PrimaryContributionAccount": "joint",
}

AUDIENCE_LABELS = {
    "governance": "Executive governance roles",
    "finance": "Finance roles",
    "membership": "Membership roles",
    "production": "Production leadership",
    "joint": "Secondary executives",
    "leadership": "Chairperson / Vice Chairperson",
}


def _phase7():
    return importlib.import_module("phase7")


def _role_allows_audience(role, audience):
    if role in SECRETARIAT_ROLES:
        # Secretaries are the official cooperative record custodians.  They may
        # read the cooperative's full controlled register, while action routes
        # remain protected by their own role rules.
        return True
    if audience == "governance":
        return role in _core.GOVERNANCE_VIEW_ROLES
    if audience == "finance":
        return role in _core.FINANCE_VIEW_ROLES
    if audience == "membership":
        return role in _core.MEMBERSHIP_VIEW_ROLES
    if audience == "production":
        return role in _core.OPERATIONS_VIEW_ROLES
    if audience == "joint":
        return role in _core.SECONDARY_EXECUTIVE_ROLES
    if audience == "leadership":
        return role in LEADERSHIP_ROLES
    return False


def _audiences_for(document_type=None, entity_type=None):
    audiences = set(TYPE_AUDIENCES.get(document_type or "", set()))
    linked = ENTITY_AUDIENCES.get(entity_type or "")
    if linked:
        audiences.add(linked)
    return audiences


def can_view_document(role, document):
    """Return whether a cooperative executive may read one document."""
    if not role or role == "Admin" or role not in _core.COOPERATIVE_EXECUTIVE_ROLES:
        return False
    if role in SECRETARIAT_ROLES:
        return True
    return any(_role_allows_audience(role, audience) for audience in _audiences_for(
        document.document_type, document.entity_type
    ))


def can_upload_document_type(role, document_type):
    """Upload rights follow the audiences the user is allowed to participate in."""
    if not role or role == "Admin" or role not in _core.COOPERATIVE_EXECUTIVE_ROLES:
        return False
    if role in SECRETARIAT_ROLES:
        return document_type in TYPE_AUDIENCES
    return any(_role_allows_audience(role, audience) for audience in TYPE_AUDIENCES.get(document_type, set()))


def allowed_document_types(role):
    return tuple(document_type for document_type in _phase7().DOCUMENT_TYPES if can_upload_document_type(role, document_type))


def allowed_entity_types(role):
    if not role or role == "Admin":
        return ()
    if role in SECRETARIAT_ROLES:
        return tuple(ENTITY_AUDIENCES.keys())
    return tuple(
        entity_type
        for entity_type, audience in ENTITY_AUDIENCES.items()
        if _role_allows_audience(role, audience)
    )


def _visibility_label(document):
    labels = ["Secretariat"]
    for audience in sorted(_audiences_for(document.document_type, document.entity_type)):
        label = AUDIENCE_LABELS.get(audience)
        if label and label not in labels:
            labels.append(label)
    return ", ".join(labels)


def _entity_model(entity_type):
    """Resolve only supported link targets and their cooperative scope column."""
    p7 = _phase7()
    core_models = {
        "Expense": _core.Expense,
        "Payment": _core.Payment,
        "Sale": _core.Sale,
        "Contribution": _core.Contribution,
        "Meeting": _core.Meeting,
        "Resolution": _core.Resolution,
        "Task": _core.Task,
        "Membership": _core.Membership,
        "Farmer": _core.Farmer,
        "Farm": _core.Farm,
        "Crop": _core.Crop,
        "Harvest": _core.Harvest,
        "Equipment": _core.Equipment,
        "Budget": p7.Budget,
        "BankReconciliation": p7.BankReconciliation,
        "ProductionInput": p7.ProductionInput,
        "EquipmentUsage": p7.EquipmentUsage,
    }
    if entity_type in core_models:
        return core_models[entity_type], "cooperative_id"

    if entity_type in {"LedgerTransaction", "FinanceReconciliation"}:
        ledger = importlib.import_module("account_ledger")
        return getattr(ledger, entity_type), "cooperative_id"

    if entity_type in {"PrimaryContributionPayment", "JointMarketContract", "PrimaryContributionAccount"}:
        joint = importlib.import_module("joint_operations")
        model = getattr(joint, entity_type, None)
        if model is None:
            return None, None
        scope_field = "secondary_cooperative_id" if hasattr(model, "secondary_cooperative_id") else "cooperative_id"
        return model, scope_field

    return None, None


def _linked_record_in_cooperative(entity_type, entity_id, cooperative_id):
    model, scope_field = _entity_model(entity_type)
    if model is None or not entity_id:
        return None
    column = getattr(model, scope_field, None)
    if column is None:
        return None
    return model.query.filter(model.id == entity_id, column == cooperative_id).first()


def _current_executive():
    access = _core.current_access()
    if not access or access.role not in _core.COOPERATIVE_EXECUTIVE_ROLES or not access.cooperative_id:
        abort(403)
    return access


def _document_register_view():
    p7 = _phase7()
    access = _current_executive()
    role = access.role
    search = request.args.get("search", "").strip().lower()
    doc_type = request.args.get("type", "").strip()

    rows = p7.CooperativeDocument.query.filter_by(cooperative_id=access.cooperative_id).order_by(
        p7.CooperativeDocument.created_at.desc()
    ).all()
    rows = [item for item in rows if can_view_document(role, item)]

    available_types = tuple(sorted({item.document_type for item in rows}))
    if doc_type and doc_type not in available_types:
        # Do not let a user use filters to probe document classes they cannot see.
        abort(403)
    if search:
        rows = [
            item for item in rows
            if search in (item.title or "").lower()
            or search in (item.original_name or "").lower()
            or search in (item.notes or "").lower()
        ]
    if doc_type:
        rows = [item for item in rows if item.document_type == doc_type]

    return render_template(
        "phase7/documents.html",
        documents=rows,
        search=request.args.get("search", "").strip(),
        doc_type=doc_type,
        document_types=available_types,
        visibility_labels={item.id: _visibility_label(item) for item in rows},
    )


def _document_download_view(document_id):
    p7 = _phase7()
    access = _current_executive()
    item = p7.CooperativeDocument.query.filter_by(
        id=document_id,
        cooperative_id=access.cooperative_id,
    ).first_or_404()
    if not can_view_document(access.role, item):
        abort(404)
    return send_file(p7._document_path(item.stored_name), as_attachment=True, download_name=item.original_name)


def _validate_upload_context(role, cooperative_id, document_type, entity_type, entity_id):
    if not can_upload_document_type(role, document_type):
        abort(403)
    if bool(entity_type) != bool(entity_id):
        return "Linked record type and ID must be supplied together.", 400
    if not entity_type:
        return None
    if entity_type not in ENTITY_AUDIENCES:
        return "Choose a supported linked record type.", 400
    if entity_type not in allowed_entity_types(role):
        abort(403)
    if _linked_record_in_cooperative(entity_type, entity_id, cooperative_id) is None:
        return "Linked record was not found in your cooperative.", 400
    return None


def _document_upload_view():
    p7 = _phase7()
    access = _current_executive()
    role = access.role
    cooperative_id = access.cooperative_id
    types = allowed_document_types(role)
    entity_types = allowed_entity_types(role)

    if request.method == "GET":
        prefilled_type = request.args.get("document_type", "").strip()
        prefilled_entity_type = request.args.get("entity_type", "").strip()
        prefilled_entity_id = _core.parse_int(request.args.get("entity_id"))
        if prefilled_type and prefilled_type not in types:
            abort(403)
        if prefilled_entity_type:
            validation = _validate_upload_context(
                role, cooperative_id, prefilled_type or (types[0] if types else ""),
                prefilled_entity_type, prefilled_entity_id,
            )
            if validation:
                return validation
        return render_template(
            "phase7/document_form.html",
            document_types=types,
            allowed_entity_types=entity_types,
        )

    title = request.form.get("title", "").strip()
    document_type = request.form.get("document_type", "").strip()
    entity_type = request.form.get("entity_type", "").strip() or None
    entity_id = _core.parse_int(request.form.get("entity_id"))
    if not title or document_type not in types:
        return "Title and an authorised document type are required.", 400

    validation = _validate_upload_context(role, cooperative_id, document_type, entity_type, entity_id)
    if validation:
        return validation

    try:
        original, stored, digest = p7._save_document(request.files.get("file"))
    except ValueError as exc:
        return str(exc), 400

    item = p7.CooperativeDocument(
        cooperative_id=cooperative_id,
        document_type=document_type,
        title=title,
        entity_type=entity_type,
        entity_id=entity_id,
        original_name=original,
        stored_name=stored,
        file_sha256=digest,
        uploaded_by_user_id=session["user_id"],
        notes=request.form.get("notes", "").strip() or None,
    )
    _core.db.session.add(item)
    _core.db.session.flush()
    _core.add_audit_log(
        "DOCUMENT_UPLOADED",
        "CooperativeDocument",
        item.id,
        f"{item.document_type}: {item.title} sha256={digest}",
        cooperative_id=cooperative_id,
    )
    _core.db.session.commit()
    return redirect(url_for("phase7.documents"))


def _context_values():
    access = _core.current_access()
    role = access.role if access else ""
    is_executive = bool(access and role in _core.COOPERATIVE_EXECUTIVE_ROLES and access.cooperative_id)
    upload_types = allowed_document_types(role) if is_executive else ()

    if role in SECRETARIAT_ROLES:
        summary = "Full cooperative record register"
    elif role in TREASURER_ROLES:
        summary = "Finance, governance and role-linked records"
    elif role in LEADERSHIP_ROLES:
        summary = "Governance, finance and authorised operational records"
    else:
        summary = "Role-authorised cooperative records"

    return {
        "can_view_document_register": is_executive,
        "can_upload_documents": bool(upload_types),
        "document_register_full_access": role in SECRETARIAT_ROLES,
        "document_access_summary": summary,
    }


def install_document_access_controls(app):
    """Install idempotent route replacements and template access context."""
    if app.extensions.get("malenge_document_access_installed"):
        return

    required = ("phase7.documents", "phase7.document_upload", "phase7.document_download")
    if not all(endpoint in app.view_functions for endpoint in required):
        raise RuntimeError("Phase 7 document routes must be registered before document access controls.")

    app.view_functions["phase7.documents"] = _core.login_required(_document_register_view)
    app.view_functions["phase7.document_upload"] = _core.login_required(_document_upload_view)
    app.view_functions["phase7.document_download"] = _core.login_required(_document_download_view)

    @app.context_processor
    def document_access_context():
        return _context_values()

    app.extensions["malenge_document_access_installed"] = True
