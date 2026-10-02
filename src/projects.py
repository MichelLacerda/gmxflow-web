import os
import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryFile
from typing import cast
from zipfile import ZIP_DEFLATED, ZipFile

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_babel import gettext as _
from gmxflow.config import GmxFlowConfig
from peewee import DateTimeField
from pydantic import ValidationError

from .auth import login_required
from .configuration import UPLOADS, fields, from_form, project_dir, to_toml
from .models import Project, database, now

bp = Blueprint("projects", __name__, url_prefix="/projects")


def render_form(project, config, validation_error=None, status=200):
    uploaded_names = {}
    if project is not None and project.config_json:
        saved = GmxFlowConfig.model_validate_json(project.config_json)
        for alias, spec in UPLOADS.items():
            section, key = spec["field"].split(".")
            path = getattr(getattr(saved, section), key)
            if (
                path
                and (
                    project_dir(current_app.config["PROJECT_ROOT"], project) / path
                ).is_file()
            ):
                uploaded_names[alias] = Path(path).name
    return render_template(
        "project_form.html",
        project=project,
        groups=fields(config),
        uploads=UPLOADS,
        uploaded_names=uploaded_names,
        validation_error=validation_error,
    ), status


def owned(project_id: str) -> Project:
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        abort(404)
    project = Project.get_or_none((Project.id == uid) & (Project.owner == g.user))
    if project is None:
        abort(404)
    return project


@bp.get("")
@login_required
def list_projects():
    projects = (
        Project.select()
        .where(Project.owner == g.user)
        .order_by(cast(DateTimeField, Project.created_at).desc())
    )
    projects = list(projects)
    downloadable_ids = {
        project.id for project in projects if outputs_dir(project) is not None
    }
    return render_template(
        "projects.html",
        projects=projects,
        downloadable_ids=downloadable_ids,
    )


def outputs_dir(project):
    directory = project_dir(current_app.config["PROJECT_ROOT"], project) / "outputs"
    return directory if directory.is_dir() and not directory.is_symlink() else None


@bp.get("/<project_id>/outputs.zip")
@login_required
def download_outputs(project_id):
    project = owned(project_id)
    directory = outputs_dir(project)
    if directory is None:
        abort(404)
    archive = TemporaryFile(mode="w+b")
    try:
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            zip_file.writestr("outputs/", b"")
            for root_name, directories, files in os.walk(directory, followlinks=False):
                root = Path(root_name)
                directories[:] = [
                    name for name in directories if not (root / name).is_symlink()
                ]
                for name in directories + files:
                    path = root / name
                    if not path.is_symlink() and (path.is_dir() or path.is_file()):
                        zip_file.write(path, path.relative_to(directory.parent))
        size = archive.tell()
        archive.seek(0)
        response = send_file(
            archive,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{project.id}-outputs.zip",
        )
        response.content_length = size
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except BaseException:
        archive.close()
        raise


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        return save_project(None)
    return render_form(None, GmxFlowConfig())


@bp.route("/<project_id>/edit", methods=["GET", "POST"])
@login_required
def edit(project_id: str):
    project: Project | None = owned(project_id)
    if project.status in ("running", "queued"):
        flash(_("Aguarde o fim da execução para editar."), "error")
        return redirect(url_for("projects.detail", project_id=project_id))
    if request.method == "POST":
        return save_project(project)
    return render_form(project, GmxFlowConfig.model_validate_json(project.config_json))


def save_project(project: Project | None):
    try:
        config = from_form(
            request.form,
            GmxFlowConfig.model_validate_json(project.config_json) if project else None,
        )
    except (ValueError, ValidationError) as exc:
        flash(_("Confira os campos: %(error)s", error=exc), "error")
        return render_form(
            project,
            GmxFlowConfig.model_validate_json(project.config_json)
            if project
            else GmxFlowConfig(),
            status=400,
        )
    if not config.project.name.strip():
        flash(_("O nome do projeto é obrigatório."), "error")
        return render_form(project, config, status=400)
    is_new = project is None
    if is_new:
        project = Project(
            id=uuid.uuid4(),
            owner=g.user,
            name=config.project.name,
            config_json="",
        )
    directory = project_dir(current_app.config["PROJECT_ROOT"], project)
    inputs = directory / "inputs"
    uploads_to_save = []
    uploaded_aliases = set()
    for alias, spec in UPLOADS.items():
        uploaded = request.files.get(alias)
        if uploaded and uploaded.filename:
            filename = uploaded.filename
            suffix = spec["extension"]
            if (
                filename != Path(filename).name
                or "\\" in filename
                or ":" in filename
                or any(ord(char) < 32 for char in filename)
                or filename in (".", "..")
                or Path(filename).suffix.lower() != suffix
            ):
                flash(
                    _(
                        "Arquivo %(name)s: use um nome simples com extensão "
                        "%(extension)s.",
                        name=alias,
                        extension=suffix,
                    ),
                    "error",
                )
                return render_form(project, config, status=400)
            if uploaded.stream.seek(0, 2) == 0:
                flash(
                    _("O arquivo %(label)s está vazio.", label=spec["label"]), "error"
                )
                return render_form(project, config, status=400)
            uploaded.stream.seek(0)
            uploaded_aliases.add(alias)
            uploads_to_save.append((uploaded, filename))
            section, key = spec["field"].split(".")
            setattr(getattr(config, section), key, f"inputs/{filename}")
    required_aliases = ["receptor", "ligand"]
    if config.input.ligand_kind == "small_molecule":
        required_aliases.extend(["mol2", "str"])
    for alias in required_aliases:
        if alias in uploaded_aliases:
            continue
        spec = UPLOADS[alias]
        section, key = spec["field"].split(".")
        existing = getattr(getattr(config, section), key)
        existing_path = directory / existing
        if (
            not existing
            or Path(existing).parent != Path("inputs")
            or existing_path.is_symlink()
            or not existing_path.is_file()
        ):
            flash(
                _("Envie o arquivo obrigatório: %(label)s.", label=spec["label"]),
                "error",
            )
            return render_form(project, config, status=400)
    input_names = [
        Path(getattr(config.input, spec["field"].split(".")[1])).name
        for spec in UPLOADS.values()
        if getattr(config.input, spec["field"].split(".")[1])
    ]
    if len(input_names) != len(set(input_names)):
        flash(_("Cada arquivo de entrada deve ter um nome diferente."), "error")
        return render_form(project, config, status=400)
    inputs.mkdir(parents=True, exist_ok=True)
    for uploaded, filename in uploads_to_save:
        uploaded.save(inputs / filename)
    config_path = directory / "config.toml"
    candidate = directory / "config.pending.toml"
    candidate.write_text(to_toml(config), encoding="utf-8")
    result = subprocess.run(
        ["gmxflow", "validate", "--config", str(candidate)],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        candidate.unlink(missing_ok=True)
        project.error = (result.stdout + result.stderr)[-8000:]
        if not is_new:
            project.status = "failed"
            project.save()
        flash(_("Configuração inválida. Veja a mensagem abaixo."), "error")
        return render_form(project, config, validation_error=project.error, status=400)
    os.replace(candidate, config_path)
    project.name = config.project.name
    project.config_json = config.model_dump_json()
    project.queue_priority = 1 if project.status == "failed" else 0
    project.status = "draft"
    project.error = ""
    project.updated_at = now()
    project.save(force_insert=is_new)
    flash(_("Projeto salvo e configuração validada."), "success")
    return redirect(url_for("projects.detail", project_id=project.id))


@bp.get("/<project_id>")
@login_required
def detail(project_id):
    project = owned(project_id)
    directory = project_dir(current_app.config["PROJECT_ROOT"], project)
    logs = (
        sorted((directory / "work" / "logs").glob("*.log"))
        if (directory / "work" / "logs").exists()
        else []
    )
    return render_template(
        "project_detail.html",
        project=project,
        logs=logs,
        has_outputs=outputs_dir(project) is not None,
    )


@bp.post("/<project_id>/clean")
@login_required
def clean(project_id):
    # Serialize cleanup with queue requests and the worker claiming a project.
    with database.atomic("IMMEDIATE"):
        project = owned(project_id)
        if project.status in ("queued", "running"):
            flash(_("Aguarde o fim da execução para limpar o projeto."), "error")
        else:
            directory = project_dir(current_app.config["PROJECT_ROOT"], project)
            try:
                result = subprocess.run(
                    ["gmxflow", "clean", "--config", str(directory / "config.toml")],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                flash(_("Falha ao limpar o projeto: %(error)s", error=exc), "error")
            else:
                if result.returncode != 0:
                    flash(
                        _(
                            "Falha ao limpar o projeto: %(error)s",
                            error=(result.stdout + result.stderr)[-8000:],
                        ),
                        "error",
                    )
                else:
                    project.status = "draft"
                    project.error = ""
                    project.queue_priority = 0
                    project.queued_at = None
                    project.started_at = None
                    project.finished_at = None
                    project.updated_at = now()
                    project.save()
                    flash(_("Projeto limpo com sucesso."), "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/<project_id>/queue")
@login_required
def queue(project_id):
    project = owned(project_id)
    if project.status in ("queued", "running"):
        flash(_("O projeto já está na fila ou em execução."), "error")
    else:
        priority = 1 if project.status == "failed" or project.queue_priority else 0
        project.status = "queued"
        project.queue_priority = priority
        project.queued_at = now()
        project.error = ""
        project.save()
        flash(_("Projeto colocado na fila."), "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.get("/<project_id>/logs/<path:name>")
@login_required
def log(project_id, name):
    project = owned(project_id)
    if name != Path(name).name or not name.endswith(".log"):
        abort(404)
    directory = project_dir(current_app.config["PROJECT_ROOT"], project)
    path = directory / "work" / "logs" / name
    if not path.is_file() or path.is_symlink():
        abort(404)
    return render_template(
        "log.html",
        project=project,
        name=name,
        content=path.read_text(errors="replace")[-100000:],
    )
