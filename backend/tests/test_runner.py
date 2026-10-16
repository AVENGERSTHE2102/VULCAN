import asyncio
import pytest
from services import runner


async def test_runner_cleanup_and_fixed_interface(monkeypatch):
    calls = []

    async def docker(*args):
        calls.append(args)
        if args[0] == "run":
            raise RuntimeError("unavailable")
        return ""

    monkeypatch.setattr(runner, "command", docker)
    r = await runner.inspect(runner.Inspection(hardened=True))
    assert r["mode"] == "Simulated"
    assert calls[-1][0:2] == ("rm", "-f")
    args = calls[0]
    assert "--read-only" in args and args[args.index("--network") + 1] == "none"
    assert "/var/run/docker.sock" not in " ".join(args)
    assert "--pids-limit" in args and "--memory" in args
    with pytest.raises(ValueError):
        runner.Inspection(hardened=True, command="id")


async def test_runner_cancellation_still_cleans_up(monkeypatch):
    calls = []

    async def docker(*args):
        calls.append(args)
        if args[0] == "run":
            raise asyncio.CancelledError()
        return ""

    monkeypatch.setattr(runner, "command", docker)
    with pytest.raises(asyncio.CancelledError):
        await runner.inspect(runner.Inspection())
    assert calls[-1][0] == "rm"
