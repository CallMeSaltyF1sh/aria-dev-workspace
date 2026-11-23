import os
import tempfile

import pytest
from fastapi.testclient import TestClient

temporary = tempfile.TemporaryDirectory(prefix="dev-workspace-tests-")
os.environ["WORKSPACE_ROOT"] = temporary.name

from devworkspace.main import app  # noqa: E402
from devworkspace.storage import DATA, WORK  # noqa: E402


@pytest.fixture
def client():
    from devworkspace.storage import assets, engine, jobs
    import shutil

    with TestClient(app) as instance:
        with engine.begin() as connection:
            connection.execute(jobs.delete())
            connection.execute(assets.delete())
        for path in DATA.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        for name in ("annotations", "frames"):
            shutil.rmtree(WORK / name, ignore_errors=True)
        yield instance


@pytest.fixture
def video():
    import subprocess

    path = DATA / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10",
            "-t",
            "1.35",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path
