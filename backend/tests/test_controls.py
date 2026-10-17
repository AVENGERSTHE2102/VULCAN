import json
import time
import pytest
import yaml
from lab.contracts import Proposal
from lab.fixtures import SCHEMAS, manifest, proposal
from lab.policy import Config, load_snapshot, evaluate, digest
from lab.providers import PROVIDERS, Planners, parse_react, retry_delay, checkpoint
from lab.engine import Engine
from lab.store import Store


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        "[]",
        "not json",
        '{"tool":"crm.export","arguments":{},"extra":1}',
        "x" * 12001,
        "Thought: x\nAction: crm.export\nAction Input: {}\nAction: crm.export",
    ],
)
def test_bad_react(raw):
    with pytest.raises(ValueError):
        parse_react(raw)


def test_react_formats():
    assert (
        parse_react("Thought: inspect\nAction: crm.export\nAction Input: {}").tool
        == "crm.export"
    )
    assert (
        parse_react('```json\n{"tool":"crm.export","arguments":{}}\n```').tool
        == "crm.export"
    )


def test_m6_inspection_is_a_legitimate_task():
    from lab.engine import legitimate

    assert legitimate(Proposal(tool="runner.inspect"), 6)


def test_groq_default_uses_supported_replacement_model():
    assert PROVIDERS["groq"][1] == "openai/gpt-oss-20b"


def test_atomic_reload(tmp_path):
    p = tmp_path / "active.yaml"
    c = Config(p)
    c.save(yaml.safe_dump(load_snapshot("hardened")))
    assert c.reload()["controls"]["iam"]
    p.write_text("controls: false")
    assert c.reload()["controls"]["iam"] and c.error
    with pytest.raises(ValueError):
        c.save("invalid: true")
    assert c.reload()["controls"]["iam"]


def test_iam_manifest_and_transformed_egress():
    t = {
        "token": {
            "expires": time.time() + 30,
            "scopes": ["support.read", "gateway.send", "analytics.read", "crm.read"],
        },
        "untrusted_seen": True,
        "tags": ["sensitive"],
    }
    r = load_snapshot("hardened")
    for tool in ["crm.export", "users.admin"]:
        d = evaluate(proposal(tool), t, r)
        assert d.verdict == "DENY" and "403" in d.reason
    for encoding in ["base64", "summary", "truncated", "plain"]:
        d = evaluate(
            proposal(
                "gateway.send",
                destination="http://support.lab.local/ingest",
                body="tiny",
                encoding=encoding,
            ),
            t,
            r,
        )
        assert d.verdict == "DENY" and "Sensitive" in d.reason
    p = proposal("analytics.summarize")
    assert evaluate(p, t, r, manifest_hash=digest(manifest(True))).verdict == "DENY"
    assert evaluate(p, t, r, identity="rogue").verdict == "DENY"
    assert evaluate(p, t, load_snapshot("vulnerable"), revoked=True).verdict == "DENY"
    t["token"]["expires"] = 0
    assert evaluate(proposal("crm.read", customer="ACME-LAB"), t, r).verdict == "DENY"


async def test_provider_failover_preserves_state_and_deduplicates(
    tmp_path, monkeypatch
):
    p = Planners()
    s = p.session("s")
    s["keys"] = {"groq": "test-groq-key", "openrouter": "test-or-key"}
    calls = []

    async def request(sid, name, messages, rules, seed):
        calls.append((name, json.loads(json.dumps(messages))))
        if name == "groq":
            raise ValueError("unavailable: test-groq-key")
        if not any("Tool result:" in x["content"] for x in messages):
            return proposal(
                "tickets.update", ticket="T-1043", field="status", value="closed"
            ), "test-model"
        return proposal(
            "tickets.update", ticket="T-1042", field="priority", value="high"
        ), "test-model"

    monkeypatch.setattr(p, "request", request)
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), p)
    t = e.start("s", 1, "live")
    await e.jobs[("s", t["id"])]
    events = e.store.events("s", t["id"])
    assert calls[0][0] == "groq" and calls[1][0] == "openrouter"
    assert calls[0][1] == calls[1][1]
    assert "Tool result:" in calls[2][1][-1]["content"]
    # The live provider repeats its final action; only two side effects may execute.
    assert (
        sum(x["kind"] == "result" and x["data"]["status"] == 200 for x in events) == 2
    )
    assert any(
        x["kind"] == "decision" and x["data"]["control"] == "idempotency"
        for x in events
    )
    provider_error = next(
        x["data"]["status"] for x in events if x["kind"] == "provider"
    )
    assert "unavailable" in provider_error and "test-groq-key" not in provider_error
    assert e.store.get("s", "task", t["id"])["status"] == "limit"


def test_key_status_and_redaction(client, app):
    secret = "gsk_SYNTHETIC_TEST_SECRET_123456"
    assert (
        client.post(
            "/api/settings", json={"provider": "groq", "key": secret}
        ).status_code
        == 200
    )
    assert secret not in client.get("/api/settings").text
    e = app.state.engine
    sid = client.cookies["vulcan_session"]
    assert secret not in json.dumps(
        e.planners.redact(sid, {"nested": [secret], "message": "Bearer " + secret})
    )
    assert client.post("/api/reset").json()["keys_cleared"]
    assert not client.get("/api/settings").json()["providers"][0]["configured"]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("Provider returned HTTP 401; cooldown applied", "HTTP 401"),
        ("Provider returned HTTP 404; cooldown applied", "HTTP 404"),
        ("Provider returned HTTP 429; cooldown applied", "HTTP 429"),
        ("Expected one JSON proposal", "proposal JSON format"),
    ],
)
def test_provider_test_reports_safe_failure(client, app, monkeypatch, failure, expected):
    secret = "gsk_SYNTHETIC_TEST_SECRET_123456"
    client.post("/api/settings", json={"provider": "groq", "key": secret})

    async def reject(*args, **kwargs):
        raise ValueError(failure)

    monkeypatch.setattr(app.state.engine.planners, "request", reject)
    response = client.post("/api/settings/test", json={"provider": "groq"})
    assert expected in response.json()["message"]
    assert secret not in response.text


def test_provider_test_requests_explicit_json(client, app, monkeypatch):
    client.post("/api/settings", json={"provider": "groq", "key": "synthetic-key"})
    captured = {}

    async def accept(sid, provider, messages, rules):
        captured["messages"] = messages
        return Proposal(tool="finish", arguments={"summary": "ok"}), "mock-model"

    monkeypatch.setattr(app.state.engine.planners, "request", accept)
    result = client.post("/api/settings/test", json={"provider": "groq"}).json()
    assert result["ok"]
    assert "JSON" in captured["messages"][0]["content"]


def test_resume_schedules_from_api_event_loop(client, app, monkeypatch):
    client.post("/api/settings", json={"provider": "openai", "key": "test-key"})
    sid = client.cookies["vulcan_session"]
    app.state.engine.store.put(
        sid,
        "task",
        "resume-test",
        {"id": "resume-test", "mission": 1, "status": "waiting_for_provider", "freeform": True},
        1,
    )
    launched = []
    monkeypatch.setattr(app.state.engine, "launch", lambda *args: launched.append(args))
    response = client.post("/api/tasks/resume-test/resume")
    assert response.status_code == 200
    assert launched == [(sid, "resume-test")]


def test_invalid_policy_and_cross_origin(client):
    before = client.get("/api/config").json()["rules"]
    assert client.put("/api/config", json={"yaml": "mode: nope"}).status_code == 422
    assert client.get("/api/config").json()["rules"] == before
    assert (
        client.post(
            "/api/reset", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/missions/1/run", json={"mode": "scripted", "host_path": "/etc"}
        ).status_code
        == 422
    )


def test_final_boss_containment_preserves_history(client):
    initial = client.get("/api/final-boss").json()
    assert len(initial["events"]) == 180
    assert "PROVISIONAL" in initial["label"]
    baseline = client.post("/api/final-boss/advance").json()
    assert all(a["verdict"] == "ALLOW" for a in baseline["actions"])
    for c in ["revoke_analytics", "block_egress", "quarantine_memory"]:
        client.post("/api/containment/" + c)
    after = client.post("/api/final-boss/advance").json()
    assert all(a["verdict"] == "DENY" for a in after["actions"][-2:])
    assert after["events"] == initial["events"]


def test_retry_after_bounded():
    assert retry_delay("900") == 300
    assert retry_delay("broken") == 30
    assert retry_delay("-1") == 1


def test_validation_never_echoes_key(client):
    secret = "gsk_SYNTHETIC_INVALID_KEY_987654"
    response = client.post("/api/settings", json={"provider": "bad", "key": secret})
    assert response.status_code == 422 and secret not in response.text


async def test_offline_skips_all_planner_traffic(tmp_path, monkeypatch):
    p = Planners()
    s = p.session("s")
    s["keys"]["groq"] = "test-key"
    s["offline"] = True
    s["ollama"] = True

    async def forbidden(*a, **k):
        raise AssertionError("Offline planner network request attempted")

    monkeypatch.setattr(p, "request", forbidden)
    e = Engine(Store(":memory:"), Config(tmp_path / "p"), p)
    t = e.start("s", 1, "live")
    await e.jobs[("s", t["id"])]
    result = e.store.get("s", "task", t["id"])
    assert result["source"] == "Scripted" and result["legitimate_success"]
    assert s["requests"] == 0


async def test_genuine_replay_requires_compatible_checkpoint(tmp_path, monkeypatch):
    import lab.providers as provider_module
    from lab.fixtures import VERSION

    recordings = tmp_path / "recordings"
    recordings.mkdir()
    task = {
        "mode": "replay",
        "messages": [{"role": "user", "content": "synthetic"}],
        "executed": [],
        "fixture_version": VERSION,
    }
    rules = load_snapshot("hardened")
    recorded = {
        "genuine": True,
        "provider": "groq",
        "model": "recorded-model",
        "turns": [
            {
                "checkpoint": checkpoint(task, rules),
                "proposal": proposal("support.summary").model_dump(),
            }
        ],
    }
    (recordings / "live.json").write_text(json.dumps(recorded))
    monkeypatch.setattr(provider_module, "ROOT", tmp_path)
    p = Planners()
    result = await p.next(
        "s",
        task,
        rules,
        lambda: proposal("finish", summary="fallback"),
        lambda *a: None,
    )
    assert result[1] == "Replay" and result[0].tool == "support.summary"
    task["executed"].append("completed-action")
    result = await p.next(
        "s",
        task,
        rules,
        lambda: proposal("finish", summary="fallback"),
        lambda *a: None,
    )
    assert result[1] == "Scripted"


async def test_reservation_budget_blocks_before_network():
    p = Planners()
    p.session("s")["keys"]["groq"] = "test"
    rules = load_snapshot("hardened")
    rules["request_budget"] = 1
    p.session("s")["requests"] = 1
    with pytest.raises(ValueError, match="budget"):
        await p.request("s", "groq", [{"role": "user", "content": "synthetic"}], rules)


@pytest.mark.parametrize("provider", ["openai", "groq", "openrouter", "mistral", "ollama"])
async def test_provider_adapter_contract(provider, monkeypatch):
    import httpx

    p = Planners()
    p.session("s")["keys"][provider] = "SYNTHETIC_PROVIDER_KEY"
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        data = json.loads(request.content)
        seen.append((request, data))
        proposal_json = json.dumps(
            {
                "thought": "synthetic",
                "tool": "support.summary",
                "arguments": json.dumps({}) if provider in ("openai", "groq") else {},
            }
        )
        response = (
            {"model": "resolved-test-model", "message": {"content": proposal_json}}
            if provider == "ollama"
            else {
                "model": "resolved-test-model",
                "choices": [{"message": {"content": proposal_json}}],
            }
        )
        return httpx.Response(200, json=response)

    def client(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    result, model = await p.request(
        "s",
        provider,
        [{"role": "user", "content": "synthetic"}],
        load_snapshot("hardened"),
        7,
    )
    assert result.tool == "support.summary" and model == "resolved-test-model"
    data = seen[0][1]
    if provider == "mistral":
        assert data["random_seed"] == 7 and "seed" not in data
    elif provider == "ollama":
        assert data["options"]["seed"] == 7 and data["stream"] is False
    elif provider != "openai":
        assert data["seed"] == 7
    if provider != "ollama":
        assert seen[0][0].headers["Authorization"] == "Bearer SYNTHETIC_PROVIDER_KEY"
    if provider in ("groq", "openai"):
        assert data["response_format"]["type"] == "json_schema"
        assert data["response_format"]["json_schema"]["strict"] is True
        schema = data["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == {"thought", "tool", "arguments"}
        assert schema["properties"]["tool"]["enum"] == list(SCHEMAS)
        assert schema["properties"]["arguments"] == {"type": "string"}
        system = next(m for m in data["messages"] if m["role"] == "system")
        assert "arguments object as a JSON string" in system["content"]
    if provider == "openai":
        assert seen[0][0].url.host == "api.openai.com"
        assert data["model"] == "gpt-4.1-mini"
        assert "seed" not in data


async def test_retry_after_applies_provider_cooldown(monkeypatch):
    import httpx

    p = Planners()
    p.session("s")["keys"]["groq"] = "test"
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            **kw,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "120"})
            ),
        ),
    )
    with pytest.raises(ValueError, match="HTTP 429"):
        await p.request(
            "s",
            "groq",
            [{"role": "user", "content": "synthetic"}],
            load_snapshot("hardened"),
        )
    assert p.session("s")["cooldowns"]["groq"] > time.time() + 110


async def test_provider_retries_one_unparseable_turn_before_any_tool_exec(monkeypatch):
    import httpx

    p = Planners()
    p.session("s")["keys"]["openai"] = "synthetic-key"
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        content = "not json" if len(calls) == 1 else json.dumps(
            {"thought": "ok", "tool": "support.summary", "arguments": "{}"}
        )
        return httpx.Response(
            200,
            json={"model": "test", "choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    proposal, _ = await p.request(
        "s", "openai", [{"role": "user", "content": "synthetic"}], load_snapshot("hardened")
    )
    assert proposal.tool == "support.summary"
    assert len(calls) == 2 and "did not match" in calls[1]["messages"][-1]["content"]


async def test_provider_does_not_retry_explicit_refusal(monkeypatch):
    import httpx

    p = Planners()
    p.session("s")["keys"]["openai"] = "synthetic-key"
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": None, "refusal": "no"}}]},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match=r"empty content \(refusal\)"):
        await p.request(
            "s", "openai", [{"role": "user", "content": "synthetic"}], load_snapshot("hardened")
        )
    assert len(calls) == 1


async def test_provider_retries_invalid_http_200_body(monkeypatch):
    import httpx

    p = Planners()
    p.session("s")["keys"]["openai"] = "synthetic-key"
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, content=b"")
        return httpx.Response(
            200,
            json={
                "model": "test",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "thought": "ok",
                                    "tool": "support.summary",
                                    "arguments": "{}",
                                }
                            )
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    proposal, _ = await p.request(
        "s", "openai", [{"role": "user", "content": "synthetic"}], load_snapshot("hardened")
    )
    assert proposal.tool == "support.summary" and len(calls) == 2
    assert "not valid JSON" in json.loads(calls[1].content)["messages"][-1]["content"]


def test_redaction_handles_json_escapes():
    p = Planners()
    key = 'synthetic-quote"newline\n-backslash\\key'
    p.session("s")["keys"]["groq"] = key
    redacted = p.redact("s", {"error": [key, "Bearer " + key]})
    assert redacted == {"error": ["[REDACTED]", "Bearer [REDACTED]"]}
