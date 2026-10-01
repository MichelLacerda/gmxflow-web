"""Single-machine queue consumer. Run exactly one worker against a data volume."""

import fcntl
import subprocess
import time
from pathlib import Path
from typing import cast

from gmxflow.config import GmxFlowConfig
from peewee import DateTimeField, IntegerField

from . import create_app
from .configuration import project_dir, to_toml
from .models import Project, database, now


def process_one(app):
    with app.app_context(), database.connection_context():
        with database.atomic("IMMEDIATE"):
            project = (
                Project.select()
                .where(Project.status == "queued")
                .order_by(
                    cast(IntegerField, Project.queue_priority).desc(),
                    cast(DateTimeField, Project.queued_at).asc(),
                )
                .first()
            )
            if project is None:
                return False
            project.status = "running"
            project.started_at = now()
            project.save()
        directory = project_dir(app.config["PROJECT_ROOT"], project)
        config_path = directory / "config.toml"
        if not config_path.is_file():
            directory.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                to_toml(GmxFlowConfig.model_validate_json(project.config_json)),
                encoding="utf-8",
            )
        log_dir = directory / "work" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "web-run.log").open("w", encoding="utf-8") as stream:
            try:
                result = subprocess.run(
                    ["gmxflow", "run", "--config", str(config_path), "--strict-inputs"],
                    cwd=directory,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                project.status = "completed" if result.returncode == 0 else "failed"
                if result.returncode == 0:
                    project.queue_priority = 0
                project.error = (
                    ""
                    if result.returncode == 0
                    else f"Execução falhou (código {result.returncode}). Veja os logs."
                )
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                project.status = "failed"
                project.error = str(exc)
                stream.write(f"\n{exc}\n")
            project.finished_at = now()
            project.save()
        return True


def main():
    app = create_app()
    lock_path = Path(app.config["PROJECT_ROOT"]) / ".worker.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with app.app_context(), database.connection_context():
            # A previous worker may have died while running a simulation.
            Project.update(
                status="failed",
                error="Worker interrompido; confira os logs antes de reenfileirar.",
            ).where(Project.status == "running").execute()
        while True:
            if not process_one(app):
                time.sleep(2)


if __name__ == "__main__":
    main()
