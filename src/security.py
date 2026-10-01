import hmac
import secrets

from flask import abort, request, session
from flask_babel import gettext as _


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def check_csrf():
    if request.method == "POST" and not hmac.compare_digest(
        request.form.get("csrf_token", ""), session.get("csrf_token", "")
    ):
        abort(400, _("Token do formulário inválido."))
