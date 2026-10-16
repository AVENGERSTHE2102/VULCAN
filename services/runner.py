import asyncio
import json
import os
import uuid
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

app = FastAPI(title="Restricted synthetic task runner")


class Inspection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hardened: bool = True


@app.get("/health")
def health():
    return {"status": "ok"}


def lint(hardened):
    return {
        "network": "none" if hardened else "vulcan_lab",
        "read_only": hardened,
        "memory_mb": 64 if hardened else 256,
        "pids_limit": 32,
        "cap_drop": "ALL",
        "no_new_privileges": True,
        "synthetic_only": True,
        "lint": []
        if hardened
        else [
            "Broad synthetic token",
            "Writable container root",
            "Expanded memory limit",
            "Internal lab network available",
        ],
    }


async def command(*args):
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), 10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Docker operation failed")
    return out.decode()


@app.post("/inspect")
async def inspect(body: Inspection):
    name = "vulcan-task-" + uuid.uuid4().hex
    limits = lint(body.hardened)
    # The fixed image contains synthetic fixtures. No model value reaches Docker arguments.
    args = [
        "run",
        "--name",
        name,
        "--rm",
        "--network",
        limits["network"],
        "--memory",
        str(limits["memory_mb"]) + "m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "32",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=8m",
        "--mount",
        "type=volume,source=vulcan-synthetic-fixtures,target=/fixtures,readonly",
        "-e",
        "LAB_TOKEN=SYNTHETIC_TASK_READ"
        if body.hardened
        else "LAB_TOKEN=SYNTHETIC_BROAD_LAB_ONLY",
    ]
    if body.hardened:
        args += ["--read-only"]
    args += [os.environ.get("TASK_IMAGE", "vulcan-task:1.2"), "python", "/inspect.py"]
    try:
        output = await command(*args)
        return {
            "mode": "Docker",
            **limits,
            "output": json.loads(output),
            "cleanup": "Container removed",
        }
    except (OSError, RuntimeError, asyncio.TimeoutError):
        return {
            "mode": "Simulated",
            "label": "SIMULATED — runner image or Docker unavailable",
            **limits,
            "cleanup": "No active task container",
        }
    finally:
        try:
            await command("rm", "-f", name)
        except (OSError, RuntimeError, asyncio.TimeoutError):
            pass
