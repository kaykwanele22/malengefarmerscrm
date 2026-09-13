from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def replace_once(text, old, new, label):
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} target, found {count}.")
    return text.replace(old, new, 1)


def regex_once(text, pattern, replacement, label):
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} target, found {count}.")
    return updated


def main():
    text = APP.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        "    has_request_context,\n    redirect,",
        "    has_request_context,\n    jsonify,\n    redirect,",
        "Flask jsonify import",
    )
    text = replace_once(
        text,
        "from sqlalchemy import func, or_, text as sql_text\n",
        "from sqlalchemy import func, or_, text as sql_text\nfrom sqlalchemy.exc import IntegrityError, SQLAlchemyError\n",
        "SQLAlchemy exception imports",
    )

    error_helpers = '''def _wants_json_error():
    """Return True when an error should use the API JSON envelope."""
    if request.path.startswith("/api/v1/"):
        return True

    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    if best != "application/json":
        return False
    return request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


def _render_branded_error(status_code, title, message):
    """Render the reusable branded error page without exposing internals."""
    destination = url_for("dashboard") if logged_in() else url_for("home")
    destination_label = "Back to Dashboard" if logged_in() else "Back to Home"
    return render_template(
        "errors/error.html",
        status_code=status_code,
        title=title,
        message=message,
        request_id=getattr(g, "request_id", None),
        destination=destination,
        destination_label=destination_label,
    )


def _error_response(status_code, title, message, headers=None):
    """Build one safe HTML or JSON error response with a request reference."""
    request_id = getattr(g, "request_id", None)
    if _wants_json_error():
        response = jsonify({
            "error": {
                "status": int(status_code),
                "title": str(title),
                "message": str(message),
                "request_id": request_id,
            }
        })
        response.status_code = int(status_code)
    else:
        response = app.make_response(_render_branded_error(status_code, title, message))
        response.status_code = int(status_code)

    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response
'''

    text = regex_once(
        text,
        r"def _render_branded_error\(status_code, title, message\):.*?(?=\n\n# =========================================================\n# APPLICATION CONTEXT PROCESSORS AND REQUEST HANDLERS)",
        error_helpers.rstrip(),
        "branded error helper block",
    )

    text = replace_once(
        text,
        '    if request.method == "POST" and response.status_code in {400, 401}:\n',
        '    if (\n            request.method == "POST"\n            and response.status_code in {400, 401}\n            and not _wants_json_error()\n    ):\n',
        "form feedback POST guard",
    )

    old_response_block = '''    # Replace simple non-form HTTP errors with a branded page
    if response.status_code in {400, 401, 403, 404, 413, 429, 500}:
        message = _plain_error_message(response)

        if message:
            titles = {
                400: "Please check the information",
                401: "Sign-in required",
                403: "Access denied",
                404: "Page not found",
                413: "Request too large",
                429: "Too many attempts",
                500: "Something went wrong",
            }
            html_response = _render_branded_error(
                response.status_code,
                titles.get(response.status_code, "Request could not be completed"),
                message,
            )
            branded = app.make_response(html_response)
            branded.status_code = response.status_code
            return branded
'''
    new_response_block = '''    # Replace simple non-form HTTP errors with a consistent HTML/JSON response.
    if response.status_code in {400, 401, 403, 404, 405, 409, 413, 422, 429, 500, 503}:
        message = _plain_error_message(response)

        if message:
            titles = {
                400: "Please check the information",
                401: "Sign-in required",
                403: "Access denied",
                404: "Page not found",
                405: "Action not allowed",
                409: "Record conflict",
                413: "Request too large",
                422: "Information could not be processed",
                429: "Too many attempts",
                500: "Something went wrong",
                503: "Service temporarily unavailable",
            }
            return _error_response(
                response.status_code,
                titles.get(response.status_code, "Request could not be completed"),
                message,
            )
'''
    text = replace_once(
        text,
        old_response_block,
        new_response_block,
        "after-request error response block",
    )

    handlers = '''# =========================================================
# ERROR HANDLERS
# =========================================================
@app.errorhandler(400)
def bad_request(error):
    """Handle malformed or invalid requests."""
    message = getattr(error, "description", None) or "The request could not be completed because some information is invalid."
    return _error_response(400, "Please check the information", message)


@app.errorhandler(401)
def unauthorized(error):
    """Handle unauthenticated requests."""
    message = getattr(error, "description", None) or "Please sign in with an authorized Malenge Farmers CRM account."
    return _error_response(401, "Sign-in required", message)


@app.errorhandler(403)
def forbidden(error):
    """Handle permission failures."""
    message = getattr(error, "description", None) or "You do not have permission to access this page."
    return _error_response(403, "Access denied", message)


@app.errorhandler(404)
def page_not_found(_error):
    """Handle unknown routes and scoped records."""
    return _error_response(404, "Page not found", "The requested page or record was not found.")


@app.errorhandler(405)
def method_not_allowed(_error):
    """Handle unsupported HTTP methods without exposing framework details."""
    return _error_response(405, "Action not allowed", "That action is not available for this page or API endpoint.")


@app.errorhandler(409)
def conflict(error):
    """Handle application-level record conflicts."""
    message = getattr(error, "description", None) or "This change conflicts with an existing CRM record."
    return _error_response(409, "Record conflict", message)


@app.errorhandler(413)
def request_too_large(_error):
    """Handle requests larger than the configured application limit."""
    return _error_response(
        413,
        "Request too large",
        "The submitted request is larger than the CRM allows. Reduce the upload size and try again.",
    )


@app.errorhandler(422)
def unprocessable(error):
    """Handle structurally valid requests whose values cannot be processed."""
    message = getattr(error, "description", None) or "The submitted information could not be processed."
    return _error_response(422, "Information could not be processed", message)


@app.errorhandler(429)
def too_many_requests(error):
    """Handle authentication throttling and other rate limits."""
    message = getattr(error, "description", None) or "Too many requests were received. Please wait and try again."
    return _error_response(429, "Too many attempts", message)


@app.errorhandler(IntegrityError)
def database_integrity_error(error):
    """Rollback failed writes and return a safe conflict message."""
    db.session.rollback()
    app.logger.warning(
        "Database integrity conflict request_id=%s method=%s path=%s error_type=%s",
        getattr(g, "request_id", None),
        request.method,
        request.path,
        type(error).__name__,
    )
    return _error_response(
        409,
        "Record conflict",
        "This change conflicts with an existing record or relationship. Review the information and try again.",
    )


@app.errorhandler(SQLAlchemyError)
def database_error(error):
    """Rollback database failures and avoid leaking connection/query details."""
    db.session.rollback()
    app.logger.error(
        "Database failure request_id=%s method=%s path=%s error_type=%s",
        getattr(g, "request_id", None),
        request.method,
        request.path,
        type(error).__name__,
    )
    return _error_response(
        503,
        "Service temporarily unavailable",
        "The CRM could not complete the database operation. Please try again shortly.",
    )


@app.errorhandler(500)
def internal_error(error):
    """Handle unexpected server failures without exposing internals."""
    db.session.rollback()
    original = getattr(error, "original_exception", None)
    app.logger.error(
        "Unhandled server error request_id=%s method=%s path=%s error_type=%s",
        getattr(g, "request_id", None),
        request.method,
        request.path,
        type(original or error).__name__,
    )
    return _error_response(
        500,
        "Something went wrong",
        "An unexpected CRM error occurred. Please try again. If it continues, share the reference shown below with the administrator.",
    )
'''

    text = regex_once(
        text,
        r"# =========================================================\n# ERROR HANDLERS\n# =========================================================.*?(?=\n\n# =========================================================\n# PHASE 7 COOPERATIVE OPERATIONS SUITE)",
        handlers.rstrip(),
        "error handler block",
    )

    if text == original:
        print("No app.py changes required.")
        return

    APP.write_text(text, encoding="utf-8")
    print("Applied error and user-feedback hardening to app.py.")


if __name__ == "__main__":
    main()
