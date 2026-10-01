"""Web interface for gmxflow."""

import os
from pathlib import Path

from flask import Flask, g, redirect, request, session, url_for
from flask_babel import Babel, get_locale
from flask_babel import lazy_gettext as _

from .models import User, database, init_database


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "development-only-secret"),
        DATABASE=os.environ.get(
            "DATABASE", str(Path(app.instance_path) / "web.sqlite3")
        ),
        PROJECT_ROOT=os.environ.get(
            "PROJECT_ROOT", str(Path(app.instance_path) / "projects")
        ),
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["PROJECT_ROOT"]).mkdir(parents=True, exist_ok=True)
    init_database(app.config["DATABASE"])

    def select_locale():
        requested = request.args.get("lang")
        if requested in ("pt_BR", "en"):
            session["locale"] = requested
        return (
            session.get("locale")
            or request.accept_languages.best_match(["pt_BR", "en"])
            or "pt_BR"
        )

    Babel().init_app(
        app,
        default_locale="pt_BR",
        locale_selector=select_locale,
        default_translation_directories=str(Path(__file__).parent / "translations"),
    )
    app.jinja_env.globals["get_locale"] = get_locale
    status_labels = {
        "draft": _("Rascunho"),
        "queued": _("Na fila"),
        "running": _("Em execução"),
        "completed": _("Concluído"),
        "failed": _("Falhou"),
    }
    app.jinja_env.globals["status_label"] = lambda status: status_labels.get(
        status, status
    )
    from .security import check_csrf, csrf_token

    app.before_request(check_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def load_user():
        database.connect(reuse_if_open=True)
        g.user = (
            User.get_or_none(User.id == session.get("user_id"))
            if session.get("user_id")
            else None
        )

    @app.teardown_request
    def close_database(_error):
        if not database.is_closed():
            database.close()

    @app.route("/")
    def index():
        return redirect(url_for("projects.list_projects" if g.user else "auth.login"))

    from .auth import bp as auth_bp
    from .projects import bp as projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(projects_bp)
    return app
