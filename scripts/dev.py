"""Install local dependencies and run the VULCAN API and dashboard together."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def command(name):
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} is required and must be on PATH")
    return path


def main():
    uv = command("uv")
    node = command("node")
    npm = command("npm")
    subprocess.run([uv, "sync", "--frozen"], cwd=ROOT, check=True)
    marker = FRONTEND / "node_modules" / ".vulcan-installed"
    if not marker.exists():
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True, shell=sys.platform == "win32")
        marker.touch()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    processes = [
        subprocess.Popen(
            [uv, "run", "uvicorn", "lab.api:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
            cwd=ROOT,
            env=env,
        ),
        subprocess.Popen(
            [node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"],
            cwd=FRONTEND,
        ),
    ]
    print("VULCAN API: http://127.0.0.1:8000  |  Dashboard: http://127.0.0.1:5173", flush=True)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
