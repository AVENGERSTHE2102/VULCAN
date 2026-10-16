import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .contracts import StrictModel
from pydantic import Field
from .engine import Engine, TERMINAL
from .fixtures import missions, VERSION
from .policy import Config, ROOT, load_snapshot, validate_config
from .providers import Planners, PROVIDERS
from .store import Store, uid
from .tools import discover


def create_app(store=None, config=None, planners=None):
    store, config, planners = (
        store or Store(),
        config or Config(),
        planners or Planners(),
    )
    engine = Engine(store, config, planners)

    @asynccontextmanager
    async def lifespan(app):
        # A restarted process must never resume a side effect from an ambiguous checkpoint.
        with store.lock, store.db:
            for row in store.db.execute(
                "SELECT session,id,data FROM objects WHERE kind='task'"
            ).fetchall():
                t = json.loads(row["data"])
                if t["status"] not in TERMINAL:
                    t["status"] = "cancelled"
                    store.put(row["session"], "task", row["id"], t, t["mission"])
        yield
        for job in engine.jobs.values():
            job.cancel()

    app = FastAPI(title="VULCAN Solo Learning Lab", version="1.2.0", lifespan=lifespan)
    app.state.engine = engine
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation responses must never echo a submitted API key.
        return JSONResponse(
            {"detail": "Invalid request fields; input omitted to protect credentials"},
            status_code=422,
        )

    allowed = {"localhost", "127.0.0.1", "api", "testserver"}

    @app.middleware("http")
    async def local_session(request, call_next):
        if request.url.hostname not in allowed:
            return JSONResponse({"detail": "Local lab host required"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            from urllib.parse import urlsplit

            if urlsplit(origin).hostname not in (
                "localhost",
                "127.0.0.1",
                "testserver",
            ):
                return JSONResponse(
                    {"detail": "Cross-origin request rejected"}, status_code=403
                )
        sid = request.cookies.get("vulcan_session")
        if not sid or len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
            sid = uid()
        request.state.sid = sid
        response = await call_next(request)
        response.set_cookie(
            "vulcan_session", sid, httponly=True, samesite="strict", max_age=86400
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def sid(r):
        return r.state.sid

    def task(r, tid):
        t = store.get(sid(r), "task", tid)
        if not t:
            raise HTTPException(404, "Task not found")
        return t

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.2.0", "fixture": VERSION}

    @app.get("/api/session")
    def session(r: Request):
        return {
            "id": sid(r),
            "settings": planners.status(sid(r)),
            "config": engine.rules(sid(r)),
            "config_error": config.error,
        }

    @app.get("/api/settings")
    def settings(r: Request):
        return planners.status(sid(r))

    @app.post("/api/settings")
    def update_settings(r: Request, body: SettingsInput):
        s = planners.session(sid(r))
        if body.provider:
            if body.key:
                s["keys"][body.provider] = body.key.get_secret_value()
            else:
                s["keys"].pop(body.provider, None)
            if body.model:
                s["models"][body.provider] = body.model
        if body.offline is not None:
            s["offline"] = body.offline
        if body.ollama is not None:
            s["ollama"] = body.ollama
        return planners.status(sid(r))

    @app.post("/api/settings/test")
    async def test_key(r: Request, body: ProviderInput):
        s = planners.session(sid(r))
        if s["offline"] or body.provider not in s["keys"]:
            raise HTTPException(400, "Provider unavailable or offline mode enabled")
        try:
            await planners.request(
                sid(r),
                body.provider,
                [
                    {
                        "role": "user",
                        "content": 'Return only {"tool":"finish","arguments":{"summary":"ok"}}',
                    }
                ],
                engine.rules(sid(r)),
            )
            return {"ok": True, "message": "Provider responded with a valid proposal"}
        except (ValueError, KeyError, TypeError, TimeoutError, httpx.HTTPError):
            return {
                "ok": False,
                "message": "Provider failed or budget exhausted; response details omitted to protect credentials",
            }

    @app.get("/api/missions")
    def mission_list():
        return missions()

    @app.post("/api/missions/{mission}/run")
    async def run(r: Request, mission: int, body: RunInput):
        if mission not in range(1, 8):
            raise HTTPException(404, "Unknown mission")
        try:
            return engine.start(sid(r), mission, body.mode, body.followup, body.seed)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/missions/{mission}/reset")
    async def reset_mission(r: Request, mission: int):
        if mission not in range(1, 8):
            raise HTTPException(404, "Unknown mission")
        await engine.reset(sid(r), mission)
        return {"reset": mission}

    @app.post("/api/reset")
    async def reset_all(r: Request):
        await engine.reset(sid(r))
        return {"reset": "session", "keys_cleared": True}

    @app.get("/api/tasks")
    def tasks(r: Request):
        return sorted(
            store.list(sid(r), "task"), key=lambda t: t["created"], reverse=True
        )

    @app.get("/api/tasks/{tid}")
    def get_task(r: Request, tid: str):
        return task(r, tid)

    @app.get("/api/tasks/{tid}/events")
    def events(r: Request, tid: str):
        task(r, tid)
        return store.events(sid(r), tid)

    @app.get("/api/tasks/{tid}/stream")
    async def stream(r: Request, tid: str, after: int = 0):
        task(r, tid)

        async def generate():
            cursor = max(after, int(r.headers.get("Last-Event-ID", "0")))
            while not await r.is_disconnected():
                for event in store.events(sid(r), tid, cursor):
                    cursor = event["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                current = store.get(sid(r), "task", tid)
                if (
                    not current
                    or current["status"] in TERMINAL
                    or current["status"] == "pending_approval"
                ):
                    yield "event: settled\ndata: {}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/tasks/{tid}/approval")
    async def approval(r: Request, tid: str, body: ApprovalInput):
        try:
            return await engine.approve(sid(r), tid, body.allow)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/config")
    def get_config(r: Request):
        return {
            "rules": engine.rules(sid(r)),
            "yaml": yaml.safe_dump(engine.rules(sid(r))),
            "error": config.error,
        }

    @app.post("/api/config/validate")
    def validate_rules(body: ConfigInput):
        try:
            return {"valid": True, "rules": validate_config(body.yaml)}
        except (ValueError, yaml.YAMLError):
            return {
                "valid": False,
                "error": "Invalid configuration; use all control booleans and positive budgets. Last valid rules retained.",
            }

    @app.put("/api/config")
    def set_config(r: Request, body: ConfigInput):
        try:
            rules = validate_config(body.yaml)
        except (ValueError, yaml.YAMLError):
            raise HTTPException(
                422, "Invalid configuration; last valid rules retained"
            ) from None
        store.put(sid(r), "config", "active", rules)
        return {"rules": rules}

    @app.post("/api/config/{snapshot}")
    def snapshot(r: Request, snapshot: str):
        if snapshot not in ("vulnerable", "hardened"):
            raise HTTPException(404, "Unknown snapshot")
        rules = load_snapshot(snapshot)
        store.put(sid(r), "config", "active", rules)
        return {"rules": rules}

    @app.get("/api/recon")
    async def recon(r: Request):
        try:
            mcp = await discover()
        except (httpx.HTTPError, KeyError, ValueError):
            mcp = {
                "available": False,
                "label": "MCP unavailable — start internal services",
            }
        return {
            "mcp": mcp,
            "memory": store.list(sid(r), "memory"),
            "tickets": store.list(sid(r), "ticket"),
            "users": store.list(sid(r), "user"),
            "token_scopes": ["support.read", "ticket:T-1042:priority"],
            "boundaries": [
                "untrusted context → planner",
                "proposal → policy",
                "task identity → data",
                "tool metadata → pin",
                "sensitivity → gateway",
                "task → sandbox",
            ],
        }

    @app.get("/api/worksheets/{mission}")
    def worksheet(r: Request, mission: int):
        return store.get(
            sid(r),
            "worksheet",
            str(mission),
            {
                "observation": "",
                "boundary": "",
                "control": "",
                "retest": "",
                "impact": "",
                "pins": [],
                "manual": 0,
            },
        )

    @app.put("/api/worksheets/{mission}")
    def save_worksheet(r: Request, mission: int, body: Worksheet):
        valid = {
            e["id"]
            for e in store.events(sid(r))
            if store.get(sid(r), "task", e["task_id"], {}).get("mission") == mission
        }
        if any(pin not in valid for pin in body.pins):
            raise HTTPException(422, "Evidence pin must belong to this mission/session")
        return store.put(sid(r), "worksheet", str(mission), body.model_dump(), mission)

    @app.get("/api/scoreboard")
    def scoreboard(r: Request):
        rows = []
        for m in missions():
            ts = store.list(sid(r), "task", m["id"])
            w = store.get(sid(r), "worksheet", str(m["id"]), {})
            baseline = any(
                t["attack_success"] and not t["config"]["controls"][m["control"]]
                for t in ts
            )
            hardened = any(
                t["legitimate_success"]
                and not t.get("config_changed")
                and t["config"]["controls"][m["control"]]
                and not t["attack_success"]
                and (
                    t["denials"] > 0
                    or m["id"] == 6
                    and t.get("inspection", {}).get("network") == "none"
                )
                for t in ts
            )
            evidence = len(set(w.get("pins", []))) >= 2
            rows.append(
                {
                    "mission": m["id"],
                    "title": m["title"],
                    "baseline": baseline,
                    "hardened_retest": hardened,
                    "evidence": evidence,
                    "automatic": 30 * baseline + 40 * hardened + 20 * evidence,
                    "manual": w.get("manual", 0),
                }
            )
        return rows

    @app.get("/api/export")
    def export(r: Request):
        return planners.redact(
            sid(r),
            {
                "fixture_version": VERSION,
                "config": engine.rules(sid(r)),
                "tasks": store.list(sid(r), "task"),
                "events": store.events(sid(r)),
                "worksheets": store.list(sid(r), "worksheet"),
            },
        )

    @app.get("/api/tasks/{tid}/recording")
    def recording(r: Request, tid: str):
        t = task(r, tid)
        turns = t["turns"]
        genuine = (
            bool(turns)
            and all(x["source"] == "Live" for x in turns)
            and t["status"] == "completed"
        )
        return {
            "genuine": genuine,
            "attack_success": t["attack_success"],
            "legitimate_success": t["legitimate_success"],
            "mission": t["mission"],
            "provider": t.get("provider"),
            "model": t.get("model"),
            "seed": t["seed"],
            "fixture_version": VERSION,
            "config": t["config"],
            "turns": turns,
            "events": store.events(sid(r), tid),
            "provenance": {
                "task": tid,
                "created": t["created"],
                "label": "Live recording"
                if genuine
                else "Mixed/Scripted transcript — not a genuine recording",
            },
        }

    @app.get("/api/recordings")
    def recordings():
        results = []
        for p in sorted((ROOT / "recordings").glob("*.json")):
            try:
                data = json.loads(p.read_text())
                if data.get("genuine"):
                    results.append(
                        {
                            "id": p.stem,
                            "mission": data["mission"],
                            "provider": data["provider"],
                            "model": data["model"],
                        }
                    )
            except (ValueError, KeyError):
                pass
        return results

    @app.post("/api/recordings/{recording_id}/restart")
    async def restart_recording(r: Request, recording_id: str):
        if not recording_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(404, "Recording not found")
        path = ROOT / "recordings" / (recording_id + ".json")
        try:
            recorded = json.loads(path.read_text())
            if not recorded.get("genuine") or recorded["fixture_version"] != VERSION:
                raise ValueError("Incompatible recording")
            rules = validate_config(yaml.safe_dump(recorded["config"]))
            if any(t["status"] not in TERMINAL for t in store.list(sid(r), "task")):
                raise HTTPException(409, "Finish or reset the active task first")
            store.put(sid(r), "config", "active", rules)
            return engine.start(
                sid(r), int(recorded["mission"]), "replay", seed=int(recorded["seed"])
            )
        except (OSError, KeyError, ValueError, TypeError, yaml.YAMLError):
            raise HTTPException(
                422, "Recording missing or incompatible; no restart performed"
            ) from None

    @app.get("/api/final-boss")
    def final_boss(r: Request):
        saved = store.get(sid(r), "incident", "timeline")
        if saved:
            return saved
        ts = [
            t
            for t in store.list(sid(r), "task")
            if t.get("turns")
            and t["status"] == "completed"
            and t["attack_success"]
            and all(x["source"] == "Live" for x in t["turns"])
        ]
        causal = store.events(sid(r), ts[-1]["id"]) if ts else []
        provenance = (
            {
                "task": ts[-1]["id"],
                "provider": ts[-1].get("provider"),
                "model": ts[-1].get("model"),
            }
            if ts
            else None
        )
        if not causal:
            for path in sorted((ROOT / "recordings").glob("*.json")):
                try:
                    recorded = json.loads(path.read_text())
                    if (
                        recorded.get("genuine")
                        and recorded.get("attack_success")
                        and recorded.get("events")
                    ):
                        causal = recorded["events"]
                        provenance = {
                            **recorded.get("provenance", {}),
                            "recording": path.name,
                            "provider": recorded["provider"],
                            "model": recorded["model"],
                        }
                        break
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        events = [
            {
                "id": f"noise-{i}",
                "sequence": i + 1,
                "source": "Synthetic noise",
                "kind": "health",
                "data": {"service": "support", "status": "ok"},
                "historical": True,
            }
            for i in range(180)
        ]
        events[38] = {
            "id": "red-herring",
            "sequence": 39,
            "source": "Synthetic red herring",
            "kind": "login",
            "data": {
                "message": "Expired lab token rejected; unrelated to the causal chain"
            },
            "historical": True,
        }
        if causal:
            for i, event in enumerate(causal[:40]):
                events[65 + i * 2] = {
                    **event,
                    "sequence": 66 + i * 2,
                    "historical": True,
                    "original_sequence": event["sequence"],
                    "recording_provenance": provenance,
                }
        else:
            for i, (kind, data) in enumerate(
                [
                    ("context", {"text": "Poisoned analytics metadata"}),
                    ("proposal", {"tool": "analytics.export_raw"}),
                    (
                        "result",
                        {
                            "destination": "local fake collector",
                            "synthetic_disclosure": True,
                        },
                    ),
                ]
            ):
                events[65 + i * 2] = {
                    "id": f"synthetic-chain-{i}",
                    "sequence": 66 + i * 2,
                    "source": "Scripted causal chain",
                    "kind": kind,
                    "data": data,
                    "historical": True,
                }
        result = {
            "label": "Recorded causal chain + synthetic noise"
            if causal
            else "PROVISIONAL — scripted causal chain; genuine recording release gate pending",
            "events": events,
            "containment": {
                "revoke_analytics": False,
                "block_egress": False,
                "quarantine_memory": False,
            },
            "actions": [],
        }
        return store.put(sid(r), "incident", "timeline", result)

    @app.post("/api/containment/{control}")
    def containment(r: Request, control: str):
        if control not in ("revoke_analytics", "block_egress", "quarantine_memory"):
            raise HTTPException(404, "Unknown containment")
        incident = final_boss(r)
        incident["containment"][control] = True
        store.put(sid(r), "incident", "timeline", incident)
        if control == "revoke_analytics":
            store.put(sid(r), "containment", "analytics", {"revoked": True})
        else:
            rules = engine.rules(sid(r))
            rules["controls"]["egress" if control == "block_egress" else "memory"] = (
                True
            )
            store.put(sid(r), "config", "active", rules)
        if control == "quarantine_memory":
            for note in store.list(sid(r), "memory"):
                note["quarantined"] = True
                store.put(sid(r), "memory", note["id"], note, 2)
        return incident

    @app.post("/api/final-boss/advance")
    def incident_action(r: Request):
        incident = final_boss(r)
        c = incident["containment"]
        for name, blocked in [
            ("analytics.export_raw", c["revoke_analytics"] or c["block_egress"]),
            ("memory.read", c["quarantine_memory"]),
        ]:
            incident["actions"].append(
                {
                    "id": uid(),
                    "tool": name,
                    "source": "Scripted incident simulation",
                    "verdict": "DENY" if blocked else "ALLOW",
                    "timestamp": time.time(),
                }
            )
        return store.put(sid(r), "incident", "timeline", incident)

    return app


from pydantic import SecretStr


class SettingsInput(StrictModel):
    provider: Literal["groq", "openrouter", "mistral"] | None = None
    key: SecretStr | None = Field(default=None, max_length=500)
    model: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[\w./:@-]+$"
    )
    offline: bool | None = None
    ollama: bool | None = None


class ProviderInput(StrictModel):
    provider: Literal["groq", "openrouter", "mistral"]


class RunInput(StrictModel):
    mode: Literal["live", "replay", "scripted"] = "live"
    followup: bool = False
    seed: int = Field(default=7, ge=0, le=2147483647)


class ApprovalInput(StrictModel):
    allow: bool


class ConfigInput(StrictModel):
    yaml: str = Field(max_length=16000)


class Worksheet(StrictModel):
    observation: str = Field(default="", max_length=6000)
    boundary: str = Field(default="", max_length=6000)
    control: str = Field(default="", max_length=6000)
    retest: str = Field(default="", max_length=6000)
    impact: str = Field(default="", max_length=6000)
    pins: list[str] = Field(default=[], max_length=100)
    manual: int = Field(default=0, ge=0, le=10)


app = create_app()
