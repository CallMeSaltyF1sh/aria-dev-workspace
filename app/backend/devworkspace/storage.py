import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, create_engine, event, select

ROOT = Path(os.environ.get("WORKSPACE_ROOT", Path(__file__).resolve().parents[3])).resolve()
DATA = ROOT / "data"
WORK = ROOT / "workspace"
DATA.mkdir(exist_ok=True, parents=True)
WORK.mkdir(exist_ok=True, parents=True)
LOCK = threading.RLock()
engine = create_engine(f"sqlite:///{WORK / 'app.db'}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def sqlite_options(connection, _):
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")


metadata = MetaData()
assets = Table(
    "assets", metadata,
    Column("id", String, primary_key=True),
    Column("path", String, unique=True, nullable=False),
    Column("fingerprint", String),
    Column("hash", String),
    Column("device", String),
    Column("info", JSON, nullable=False),
    Column("study", JSON, nullable=False),
    Column("missing", Integer, default=0),
)
jobs = Table(
    "jobs", metadata, Column("id", String, primary_key=True),
    Column("asset_id", String, nullable=False), Column("kind", String, nullable=False),
    Column("key", String, nullable=False), Column("status", String, nullable=False),
    Column("result", JSON), Column("error", String),
)


def source_path(relative: str, *, exists=False) -> Path:
    raw = DATA / relative
    # Resolve each component before any file operation and reject all symlinks.
    if Path(relative).is_absolute() or any(part in {"..", "."} for part in Path(relative).parts):
        raise ValueError("Choose a path inside data/.")
    if not raw.resolve().is_relative_to(DATA):
        raise ValueError("Path must stay inside data/.")
    if raw == DATA:
        return DATA
    if any(part.is_symlink() for part in [raw, *raw.parents] if part != DATA.parent):
        raise ValueError("Symbolic links cannot be managed.")
    if exists and not raw.exists():
        raise FileNotFoundError("Source file is missing. Scan data/ to refresh.")
    return raw


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text())


def asset_row(asset_id):
    with engine.connect() as connection:
        row = connection.execute(select(assets).where(assets.c.id == asset_id)).mappings().first()
        if row is None:
            raise FileNotFoundError("Recording not found.")
        return dict(row)


def draft_path(asset_id):
    return WORK / "annotations" / asset_id / "draft.json"
