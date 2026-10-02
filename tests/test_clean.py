import subprocess
from unittest.mock import patch

import pytest
from gmxflow.config import GmxFlowConfig
from test_flow import csrf, register

from src import create_app
from src.configuration import project_dir, to_toml
from src.models import Project, User, now


@pytest.fixture
def clean_project(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "clean@example.com")
    with app.app_context():
        project = Project.create(
            owner=User.get(User.email == "clean@example.com"),
            name="Clean",
            config_json=GmxFlowConfig().model_dump_json(),
            status="failed",
            error="Previous failure",
            queue_priority=1,
            queued_at=now(),
            started_at=now(),
            finished_at=now(),
        )
        directory = project_dir(app.config["PROJECT_ROOT"], project)
    directory.mkdir(parents=True)
    (directory / "config.toml").write_text(to_toml(GmxFlowConfig()))
    return app, client, project, directory


def test_clean_runs_command_and_preserves_inputs_outputs_templates(clean_project):
    app, client, project, directory = clean_project
    for name in (
        "inputs/receptor.pdb",
        "outputs/report.html",
        "work/prod/md.mdp",
        "work/prod/md.xtc",
        "work/logs/web-run.log",
        "work/state.json",
    ):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")
    url = f"/projects/{project.id}/clean"
    assert url in client.get(f"/projects/{project.id}").get_data(as_text=True)
    response = client.post(
        url, data={"csrf_token": csrf(client)}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "Projeto limpo com sucesso." in response.get_data(as_text=True)
    for name in (
        "inputs/receptor.pdb",
        "outputs/report.html",
        "work/prod/md.mdp",
        "config.toml",
    ):
        assert (directory / name).is_file()
    for name in ("work/prod/md.xtc", "work/logs/web-run.log", "work/state.json"):
        assert not (directory / name).exists()
    with app.app_context():
        saved = Project.get_by_id(project.id)
        assert saved.status == "draft"
        assert saved.error == "" and saved.queue_priority == 0
        assert saved.queued_at is saved.started_at is saved.finished_at is None


@pytest.mark.parametrize("status", ["queued", "running"])
def test_clean_blocks_active_projects(clean_project, status):
    app, client, project, _ = clean_project
    with app.app_context():
        project.status = status
        project.save()
    url = f"/projects/{project.id}/clean"
    assert url not in client.get(f"/projects/{project.id}").get_data(as_text=True)
    with patch("src.projects.subprocess.run") as run:
        response = client.post(
            url, data={"csrf_token": csrf(client)}, follow_redirects=True
        )
        run.assert_not_called()
    assert "Aguarde o fim da execução para limpar" in response.get_data(as_text=True)


def test_clean_requires_owner_and_csrf(clean_project):
    app, client, project, _ = clean_project
    url = f"/projects/{project.id}/clean"
    other = app.test_client()
    register(other, "other-clean@example.com")
    with patch("src.projects.subprocess.run") as run:
        assert client.get(url).status_code == 405
        assert client.post(url).status_code == 400
        assert other.post(url, data={"csrf_token": csrf(other)}).status_code == 404
        anonymous = app.test_client()
        anonymous.get("/login")
        assert (
            anonymous.post(url, data={"csrf_token": csrf(anonymous)}).status_code == 302
        )
        run.assert_not_called()


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_clean_reports_failures_without_resetting_project(clean_project, failure):
    app, client, project, directory = clean_project
    with patch("src.projects.subprocess.run") as run:
        if failure == "exit":
            run.return_value = subprocess.CompletedProcess([], 1, "", "clean failed")
        elif failure == "timeout":
            run.side_effect = subprocess.TimeoutExpired("gmxflow", 60)
        else:
            run.side_effect = FileNotFoundError("gmxflow")
        response = client.post(
            f"/projects/{project.id}/clean",
            data={"csrf_token": csrf(client)},
            follow_redirects=True,
        )
        run.assert_called_once_with(
            ["gmxflow", "clean", "--config", str(directory / "config.toml")],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    assert "Falha ao limpar o projeto:" in response.get_data(as_text=True)
    with app.app_context():
        saved = Project.get_by_id(project.id)
        assert saved.status == "failed"
        assert saved.error == "Previous failure" and saved.queue_priority == 1
