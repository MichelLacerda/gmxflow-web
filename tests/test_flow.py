import io
import tomllib

from gmxflow.config import GmxFlowConfig

from src import create_app
from src.configuration import fields
from src.models import Project
from src.worker import process_one


def csrf(client):
    with client.session_transaction() as session:
        token = session.get("csrf_token")
    if token is None:
        client.get("/projects")
        with client.session_transaction() as session:
            token = session["csrf_token"]
    return token


def form(client, name):
    client.get("/projects/new")
    data = {"csrf_token": csrf(client)}
    for _, _, group in fields(GmxFlowConfig()):
        for field in group:
            value = field["value"]
            if field["type"] == "bool":
                if value:
                    data[field["name"]] = "on"
            elif field["type"] == "list":
                data[field["name"]] = ",".join(value)
            else:
                data[field["name"]] = str(value)
    data["project.name"] = name
    return data


def with_pdb_files(data):
    data["receptor"] = (io.BytesIO(b"HEADER\n"), "receptor.pdb")
    data["ligand"] = (io.BytesIO(b"HEADER\n"), "ligante.pdb")
    return data


def register(client, email):
    client.get("/register")
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client),
            "email": email,
            "password": "longpassword123",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert response.status_code == 302


def test_projects_are_private_and_failed_job_releases_queue(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    first = app.test_client()
    register(first, "first@example.com")
    response = first.post(
        "/projects/new", data=with_pdb_files(form(first, "first run"))
    )
    assert response.status_code == 302
    project_id = response.location.rsplit("/", 1)[-1]
    assert (
        next((tmp_path / "projects").glob("*")) / project_id / "config.toml"
    ).is_file()
    first.post(f"/projects/{project_id}/queue", data={"csrf_token": csrf(first)})

    second = app.test_client()
    register(second, "second@example.com")
    assert second.get(f"/projects/{project_id}").status_code == 404
    assert second.get(f"/projects/{project_id}/logs/web-run.log").status_code == 404
    assert (
        second.post(
            f"/projects/{project_id}/queue", data={"csrf_token": csrf(second)}
        ).status_code
        == 404
    )

    assert process_one(app)
    with app.app_context():
        project = Project.get_by_id(project_id)
        assert project.status == "failed"  # the placeholder PDB contents cannot run
    assert first.get(f"/projects/{project_id}/logs/web-run.log").status_code == 200
    first.post(f"/projects/{project_id}/queue", data={"csrf_token": csrf(first)})
    with app.app_context():
        project = Project.get_by_id(project_id)
        assert project.status == "queued" and project.queue_priority == 1


def test_invalid_configuration_is_not_persisted(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "person@example.com")
    data = with_pdb_files(form(client, "bad run"))
    data["input.ph"] = "20"
    assert client.post("/projects/new", data=data).status_code == 400
    with app.app_context():
        assert Project.select().count() == 0


def test_upload_names_are_preserved_and_paths_are_not_editable(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "uploads@example.com")
    page = client.get("/projects/new").get_data(as_text=True)
    assert page.index("Projeto</summary>") < page.index("Arquivos de entrada</summary>")
    for select_name in (
        "force_field.name",
        "force_field.water",
        "box.type",
        "mdrun.pin",
    ):
        assert f'<select name="{select_name}"' in page
    assert 'name="input.receptor_pdb"' not in page
    data = form(client, "uploaded")
    data["input.receptor_pdb"] = "../../outside.pdb"
    data["receptor"] = (io.BytesIO(b"HEADER\n"), "Meu receptor.pdb")
    data["ligand"] = (io.BytesIO(b"HEADER\n"), "Ligante teste.pdb")
    response = client.post("/projects/new", data=data)
    assert response.status_code == 302
    project_id = response.location.rsplit("/", 1)[-1]
    folder = next((tmp_path / "projects").glob("*")) / project_id
    assert (folder / "inputs" / "Meu receptor.pdb").is_file()
    with (folder / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    assert config["input"]["receptor_pdb"] == "inputs/Meu receptor.pdb"
    assert config["input"]["ligand_pdb"] == "inputs/Ligante teste.pdb"
    assert "Meu receptor.pdb" in client.get(f"/projects/{project_id}/edit").get_data(
        as_text=True
    )


def test_catalogs_switch_language_and_keep_choice_in_session(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    assert "Entrar" in client.get("/login").get_data(as_text=True)
    assert "Sign in" in client.get("/login?lang=en").get_data(as_text=True)
    assert "Sign up" in client.get("/register").get_data(as_text=True)
    assert "Entrar" in client.get("/login?lang=pt_BR").get_data(as_text=True)


def test_required_inputs_for_create_and_edit(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "required@example.com")

    response = client.post("/projects/new", data=form(client, "missing"))
    assert response.status_code == 400
    assert "Envie o arquivo obrigatório: Receptor PDB." in response.get_data(
        as_text=True
    )
    with app.app_context():
        assert Project.select().count() == 0

    data = with_pdb_files(form(client, "molecule"))
    data["input.ligand_kind"] = "small_molecule"
    response = client.post("/projects/new", data=data)
    assert response.status_code == 400
    assert "Envie o arquivo obrigatório: Ligante MOL2." in response.get_data(
        as_text=True
    )

    response = client.post(
        "/projects/new", data=with_pdb_files(form(client, "peptide"))
    )
    assert response.status_code == 302
    project_id = response.location.rsplit("/", 1)[-1]
    response = client.post(f"/projects/{project_id}/edit", data=form(client, "edited"))
    assert response.status_code == 302  # uploaded files can be reused
    folder = next((tmp_path / "projects").glob("*")) / project_id
    (folder / "inputs" / "ligante.pdb").unlink()
    response = client.post(
        f"/projects/{project_id}/edit", data=form(client, "edited again")
    )
    assert response.status_code == 400
    assert "Envie o arquivo obrigatório: Ligante PDB." in response.get_data(
        as_text=True
    )


def test_outputs_zip_download_is_complete_and_private(tmp_path):
    from zipfile import ZipFile

    from src.configuration import project_dir
    from src.models import User

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "outputs@example.com")
    with app.app_context():
        project = Project.create(
            owner=User.get(User.email == "outputs@example.com"),
            name="Results",
            config_json=GmxFlowConfig().model_dump_json(),
        )
        directory = project_dir(app.config["PROJECT_ROOT"], project)
    url = f"/projects/{project.id}/outputs.zip"
    assert client.get(url).status_code == 404
    assert url not in client.get("/projects").get_data(as_text=True)
    outputs = directory / "outputs"
    (outputs / "nested" / "empty").mkdir(parents=True)
    (outputs / "report.html").write_text("<h1>Results</h1>")
    (outputs / "nested" / "data.bin").write_bytes(b"\x00\xff\x01")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    (outputs / "secret.txt").symlink_to(secret)
    (outputs / "external").symlink_to(tmp_path, target_is_directory=True)
    response = client.get(url)
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert f"{project.id}-outputs.zip" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "private, no-store"
    with ZipFile(io.BytesIO(response.data)) as archive:
        assert set(archive.namelist()) == {
            "outputs/",
            "outputs/report.html",
            "outputs/nested/",
            "outputs/nested/data.bin",
            "outputs/nested/empty/",
        }
        assert archive.read("outputs/nested/data.bin") == b"\x00\xff\x01"
        assert archive.read("outputs/report.html") == b"<h1>Results</h1>"
    response.close()
    assert url in client.get("/projects").get_data(as_text=True)
    assert url in client.get(f"/projects/{project.id}").get_data(as_text=True)
    assert "Download reports (ZIP)" in client.get("/projects?lang=en").get_data(
        as_text=True
    )
    second = app.test_client()
    register(second, "other@example.com")
    assert second.get(url).status_code == 404
    assert app.test_client().get(url).status_code == 302
    assert client.get("/projects/invalid/outputs.zip").status_code == 404


def test_outputs_zip_rejects_symlink_root_and_supports_empty_folder(tmp_path):
    from zipfile import ZipFile

    from src.configuration import project_dir
    from src.models import User

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "db.sqlite"),
            "PROJECT_ROOT": str(tmp_path / "projects"),
        }
    )
    client = app.test_client()
    register(client, "empty@example.com")
    with app.app_context():
        project = Project.create(
            owner=User.get(User.email == "empty@example.com"),
            name="Empty",
            config_json=GmxFlowConfig().model_dump_json(),
        )
        directory = project_dir(app.config["PROJECT_ROOT"], project)
    directory.mkdir(parents=True)
    outputs = directory / "outputs"
    outputs.symlink_to(tmp_path, target_is_directory=True)
    url = f"/projects/{project.id}/outputs.zip"
    assert client.get(url).status_code == 404
    assert url not in client.get("/projects").get_data(as_text=True)
    outputs.unlink()
    outputs.mkdir()
    response = client.get(url)
    with ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ["outputs/"]
    response.close()
