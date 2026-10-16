"""Start lab-local MCP and fake sinks; stop both on Ctrl-C."""

import os
import subprocess
import sys
import time

processes = []
try:
    for service, port in [("mcp", "8001"), ("sinks", "8002")]:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    f"services.{service}:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    port,
                    "--no-access-log",
                ],
                env={**os.environ, "PYTHONPATH": "backend:."},
            )
        )
    while all(p.poll() is None for p in processes):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for p in processes:
        p.terminate()
    for p in processes:
        p.wait()
