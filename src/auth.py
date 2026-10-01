from functools import wraps

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _
from werkzeug.security import check_password_hash, generate_password_hash

from .models import User

bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if (
            not email
            or "@" not in email
            or not request.form.get("first_name", "").strip()
            or not request.form.get("last_name", "").strip()
            or len(password) < 12
        ):
            flash(
                _(
                    "Informe nome, sobrenome, e-mail válido e senha de pelo menos "
                    "12 caracteres."
                ),
                "error",
            )
        elif User.get_or_none(User.email == email):
            flash(_("Este e-mail já está cadastrado."), "error")
        else:
            user = User.create(
                email=email,
                password_hash=generate_password_hash(password),
                first_name=request.form["first_name"].strip(),
                last_name=request.form["last_name"].strip(),
                entity=request.form.get("entity", "").strip(),
                course=request.form.get("course", "").strip(),
                research_area=request.form.get("research_area", "").strip(),
            )
            locale = session.get("locale")
            session.clear()
            if locale:
                session["locale"] = locale
            session["user_id"] = str(user.id)
            return redirect(url_for("projects.list_projects"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.get_or_none(
            User.email == request.form.get("email", "").strip().lower()
        )
        if user and check_password_hash(
            user.password_hash, request.form.get("password", "")
        ):
            locale = session.get("locale")
            session.clear()
            if locale:
                session["locale"] = locale
            session["user_id"] = str(user.id)
            return redirect(url_for("projects.list_projects"))
        flash(_("E-mail ou senha inválidos."), "error")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        if (
            not request.form.get("first_name", "").strip()
            or not request.form.get("last_name", "").strip()
        ):
            flash(_("Nome e sobrenome são obrigatórios."), "error")
        else:
            for field in (
                "first_name",
                "last_name",
                "entity",
                "course",
                "research_area",
            ):
                setattr(g.user, field, request.form.get(field, "").strip())
            password = request.form.get("password", "")
            if password:
                if len(password) < 12:
                    flash(_("A nova senha deve ter pelo menos 12 caracteres."), "error")
                    return render_template("profile.html")
                g.user.password_hash = generate_password_hash(password)
            g.user.save()
            flash(_("Perfil atualizado."), "success")
            return redirect(url_for("auth.profile"))
    return render_template("profile.html")
