import uuid
from datetime import UTC, datetime
from typing import cast

from peewee import (
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
    UUIDField,
)

database = SqliteDatabase(
    None, pragmas={"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000}
)


def now():
    return datetime.now(UTC)


class Base(Model):
    # Peewee replaces field descriptors with values on model instances.
    id = cast(uuid.UUID, UUIDField(primary_key=True, default=uuid.uuid4))

    class Meta:
        database = database


class User(Base):
    email = cast(str, CharField(unique=True))
    password_hash = cast(str, CharField())
    first_name = cast(str, CharField())
    last_name = cast(str, CharField())
    entity = cast(str, CharField(default=""))
    course = cast(str, CharField(default=""))
    research_area = cast(str, CharField(default=""))
    role = cast(str, CharField(default="user"))
    created_at = cast(datetime, DateTimeField(default=now))


class Project(Base):
    owner = cast(User, ForeignKeyField(User, backref="projects", on_delete="CASCADE"))
    name = cast(str, CharField())
    config_json = cast(str, TextField())
    status = cast(str, CharField(default="draft"))
    error = cast(str, TextField(default=""))
    queue_priority = cast(int, IntegerField(default=0))
    queued_at = cast(datetime | None, DateTimeField(null=True))
    started_at = cast(datetime | None, DateTimeField(null=True))
    finished_at = cast(datetime | None, DateTimeField(null=True))
    created_at = cast(datetime, DateTimeField(default=now))
    updated_at = cast(datetime, DateTimeField(default=now))


def init_database(path):
    database.init(path)
    with database.connection_context():
        database.create_tables([User, Project])
