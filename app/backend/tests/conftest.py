import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

temporary = tempfile.TemporaryDirectory(prefix="dev-workspace-tests-")
os.environ["WORKSPACE_ROOT"] = temporary.name
# Tests save prompt versions; keep them away from the repository's prompts/.
REPO_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
PROMPTS = Path(temporary.name) / "prompts"
os.environ["PROMPTS_DIR"] = str(PROMPTS)

from devworkspace.main import app  # noqa: E402
from devworkspace.storage import DATA, VRS, WORK  # noqa: E402


@pytest.fixture
def client():
    from devworkspace.storage import assets, engine, jobs
    import shutil

    with TestClient(app) as instance:
        with engine.begin() as connection:
            connection.execute(jobs.delete())
            connection.execute(assets.delete())
        for path in [*DATA.iterdir(), *VRS.iterdir()]:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        for name in ("annotations", "frames", "exports"):
            shutil.rmtree(WORK / name, ignore_errors=True)
        shutil.rmtree(PROMPTS, ignore_errors=True)
        shutil.copytree(REPO_PROMPTS, PROMPTS)
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
