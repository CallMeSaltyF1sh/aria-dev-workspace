"""Start the local Data Library; stop both processes with Ctrl+C."""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production",
        action="store_true",
        help="Serve an existing frontend build on :8000",
    )
    options = parser.parse_args()
    python = ROOT / "app/backend/.venv/bin/python"
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            parser.error(f"{executable} is missing; see app/README.md")
    if not python.exists():
        parser.error("Backend environment missing; see app/README.md")
    if options.production and not (ROOT / "app/frontend/dist/index.html").exists():
        parser.error("Build the frontend first; see app/README.md")
    for port in [8000] if options.production else [8000, 5173]:
        with socket.socket() as connection:
            connection.settimeout(0.2)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                parser.error(
                    f"Port {port} is already in use. Stop the existing service first."
                )
    npm = ["fnm", "exec", "--using", "24", "npm"] if shutil.which("fnm") else ["npm"]
    children = []

    def stop(_signum=None, _frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(
            subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "devworkspace.main:app",
                    "--app-dir",
                    "app/backend",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=ROOT,
                start_new_session=True,
            )
        )
        for _ in range(100):
            if children[0].poll() is not None:
                raise RuntimeError("Backend stopped. Check the error above.")
            try:
                with urlopen(
                    "http://127.0.0.1:8000/api/health", timeout=0.2
                ) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Backend did not become ready.")
        if not options.production:
            children.append(
                subprocess.Popen(
                    [
                        *npm,
                        "run",
                        "dev",
                        "--prefix",
                        "app/frontend",
                        "--",
                        "--port",
                        "5173",
                        "--strictPort",
                    ],
                    cwd=ROOT,
                    start_new_session=True,
                )
            )
        print(
            "Open http://127.0.0.1:" + ("8000" if options.production else "5173"),
            flush=True,
        )
        while all(process.poll() is None for process in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in children:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, FileNotFoundError) as error:
        sys.exit(str(error))
