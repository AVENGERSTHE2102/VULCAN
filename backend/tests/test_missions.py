import asyncio
import pytest
from lab.engine import Engine
from lab.policy import Config, load_snapshot
from lab.providers import Planners
from lab.store import Store
from services.mcp import app as mcp_app
from services.sinks import app as sink_app
import httpx


@pytest.fixture
def local_services(monkeypatch):
    original = httpx.AsyncClient

    def client(*a, **kw):
        class LocalClient(original):
            async def post(self, url, **kwargs):
                app = mcp_app if "8001" in url else sink_app if "8002" in url else None
                if app:
                    async with original(
                        transport=httpx.ASGITransport(app=app), base_url="http://local"
                    ) as c:
                        return await c.post(
                            "/mcp" if app is mcp_app else "/ingest", **kwargs
                        )
                raise httpx.ConnectError("runner unavailable")

        return LocalClient(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)


async def settle(engine, sid, mission, followup=False):
    t = engine.start(sid, mission, "scripted", followup)
    await engine.jobs[(sid, t["id"])]
    return engine.store.get(sid, "task", t["id"])


@pytest.mark.parametrize("mission", range(1, 8))
async def test_vulnerable_and_hardened(mission, tmp_path, local_services):
    engine = Engine(Store(":memory:"), Config(tmp_path / "rules"), Planners())
    sid = "learner"
    engine.store.put(sid, "config", "active", load_snapshot("vulnerable"))
    baseline = await settle(engine, sid, mission)
    assert baseline["status"] == "completed"
    assert baseline["attack_success"], baseline
    assert baseline["legitimate_success"]
    engine.store.put(sid, "config", "active", load_snapshot("hardened"))
    hardened = await settle(engine, sid, mission)
    assert hardened["status"] == "completed"
    assert hardened["legitimate_success"]
    assert not hardened["attack_success"]
    if mission == 6:
        assert hardened["inspection"]["mode"] == "Simulated"
        assert hardened["inspection"]["network"] == "none"
    else:
        assert hardened["denials"] > 0
    if mission == 1:
        results = [
            e["data"]
            for e in engine.store.events(sid, hardened["id"])
            if e["kind"] == "result"
        ]
        assert results[-1]["data"]["id"] == "T-1042"
        assert results[-1]["data"]["priority"] == "high"


async def test_memory_poison_two_tasks_and_quarantine(tmp_path, local_services):
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), Planners())
    await settle(e, "s", 2)
    later = await settle(e, "s", 2, True)
    assert later["poisoned"] and later["attack_success"]
    e.store.put("s", "config", "active", load_snapshot("hardened"))
    retest = await settle(e, "s", 2, True)
    assert not retest["poisoned"] and not retest["attack_success"]
    assert all(n["quarantined"] for n in e.store.list("s", "memory"))


async def test_approval_never_auto_executes_and_rechecks(tmp_path, local_services):
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), Planners())
    r = load_snapshot("vulnerable")
    r["controls"]["approval"] = True
    e.store.put("s", "config", "active", r)
    t = await settle(e, "s", 4)
    assert t["status"] == "pending_approval"
    assert not t["executed"]
    await asyncio.sleep(0.05)
    assert not e.store.get("s", "task", t["id"])["executed"]
    e.store.put("s", "config", "active", load_snapshot("hardened"))
    await e.approve("s", t["id"], True)
    await e.jobs[("s", t["id"])]
    t = e.store.get("s", "task", t["id"])
    assert not t["attack_success"] and t["legitimate_success"]


async def test_reset_isolation_and_memory_ttl(tmp_path, local_services):
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), Planners())
    await settle(e, "a", 1)
    await settle(e, "a", 2)
    await settle(e, "b", 1)
    e.planners.session("a")["keys"]["groq"] = "test-secret"
    await e.reset("a", 1)
    assert not e.store.list("a", "task", 1)
    assert e.store.list("a", "memory") and e.store.list("b", "task")
    assert e.planners.session("a")["keys"]
    for n in e.store.list("a", "memory"):
        n["expires"] = 0
        e.store.put("a", "memory", n["id"], n, 2)
    t = await settle(e, "a", 2, True)
    assert not t["poisoned"]
    await e.reset("a")
    assert not e.planners.session("a")["keys"] and not e.store.events("a")
    assert e.store.list("b", "task")


async def test_complete_offline_run_with_external_sockets_disabled(
    tmp_path, local_services, monkeypatch
):
    import socket

    original = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in (
            "127.0.0.1",
            "::1",
            "localhost",
        ):
            raise AssertionError("External network disabled during offline acceptance")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), Planners())
    e.planners.session("offline")["offline"] = True
    e.planners.session("offline")["keys"]["groq"] = "SYNTHETIC_UNUSED_KEY"
    for mode in ("vulnerable", "hardened"):
        e.store.put("offline", "config", "active", load_snapshot(mode))
        for mission in range(1, 8):
            task = e.start("offline", mission, "live")
            await e.jobs[("offline", task["id"])]
            result = e.store.get("offline", "task", task["id"])
            assert result["status"] == "completed" and result["legitimate_success"]
            assert result["source"] == "Scripted"
            assert result["attack_success"] == (mode == "vulnerable")
    assert e.planners.session("offline")["requests"] == 0
