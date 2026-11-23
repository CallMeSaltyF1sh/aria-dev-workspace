"""Run the local API and Vite development server."""
import signal
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
backend = root / "app/backend"
children = []
try:
    children.append(subprocess.Popen(
        [str(backend / ".venv/bin/python"), "-m", "uvicorn", "devworkspace.main:app",
         "--host", "127.0.0.1", "--port", "8000"], cwd=backend))
    children.append(subprocess.Popen(["npm", "run", "dev"], cwd=root / "app/frontend"))
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    children[0].wait()
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
