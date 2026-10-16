import asyncio
import json
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
import httpx
from .contracts import Proposal
from .policy import ROOT, digest

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant"),
    "openrouter": (
        "https://openrouter.ai/api/v1/chat/completions",
        "meta-llama/llama-3.1-8b-instruct",
    ),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "mistral-small-latest"),
}


def parse_react(raw):
    if not isinstance(raw, str) or len(raw) > 12000:
        raise ValueError("Planner output exceeds bounded parser limits")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.fullmatch(
            r"Thought:\s*(.{0,3000}?)\s*Action:\s*([\w.]{1,80})\s*Action Input:\s*(\{.*\})",
            text,
            re.S,
        )
        if not match:
            raise ValueError(
                "Expected one JSON proposal or bounded Thought/Action/Action Input"
            ) from None
        data = {
            "thought": match[1],
            "tool": match[2],
            "arguments": json.loads(match[3]),
        }
    return Proposal.model_validate(data)


def retry_delay(value):
    try:
        return min(300, max(1, float(value)))
    except (ValueError, TypeError):
        try:
            return min(
                300, max(1, parsedate_to_datetime(value).timestamp() - time.time())
            )
        except (ValueError, TypeError, OverflowError):
            return 30


class Planners:
    def __init__(self):
        self.sessions = {}

    def session(self, sid):
        return self.sessions.setdefault(
            sid,
            {
                "keys": {},
                "models": {},
                "cooldowns": {},
                "requests": 0,
                "tokens": 0,
                "offline": False,
                "ollama": False,
            },
        )

    def redact(self, sid, value):
        if isinstance(value, str):
            for key in self.session(sid)["keys"].values():
                value = value.replace(key, "[REDACTED]")
            return re.sub(r"(?:gsk_|sk-)[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        if isinstance(value, dict):
            return {self.redact(sid, k): self.redact(sid, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(sid, v) for v in value]
        return value

    def status(self, sid):
        s = self.session(sid)
        return {
            "providers": [
                {
                    "name": name,
                    "configured": name in s["keys"],
                    "model": s["models"].get(name, default[1]),
                    "cooldown_seconds": max(
                        0, int(s["cooldowns"].get(name, 0) - time.time())
                    ),
                }
                for name, default in PROVIDERS.items()
            ],
            "offline": s["offline"],
            "ollama": s["ollama"],
            "requests": s["requests"],
            "tokens_reserved": s["tokens"],
            "quota_hint": "Provider limits and prices vary. Budgets reserve input estimate plus 1,200 output tokens per call; failures also consume reservations.",
            "privacy": "Live mode sends synthetic context and model output to your selected planner provider under its terms. Keys stay in server memory, are never returned, and clear on global reset or server restart. Offline mode sends no planner requests. Do not enter real customer data or production credentials.",
        }

    async def request(self, sid, provider, messages, rules, seed=7):
        s = self.session(sid)
        model = s["models"].get(
            provider, "qwen2.5:3b" if provider == "ollama" else PROVIDERS[provider][1]
        )
        reserve = len(json.dumps(messages).encode()) + 1200
        if (
            s["requests"] >= rules["request_budget"]
            or s["tokens"] + reserve > rules["token_budget"]
        ):
            raise ValueError("Session request/token budget exhausted")
        s["requests"] += 1
        s["tokens"] += reserve
        async with (
            asyncio.timeout(15),
            httpx.AsyncClient(
                timeout=httpx.Timeout(12, connect=1.5), trust_env=False
            ) as client,
        ):
            if provider == "ollama":
                import os

                response = await client.post(
                    os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
                    + "/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "format": "json",
                        "options": {"seed": seed, "num_predict": 1200},
                    },
                )
            else:
                response = await client.post(
                    PROVIDERS[provider][0],
                    headers={"Authorization": "Bearer " + s["keys"][provider]},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": 1200,
                        ("random_seed" if provider == "mistral" else "seed"): seed,
                    },
                )
        if response.status_code >= 400:
            s["cooldowns"][provider] = time.time() + retry_delay(
                response.headers.get("Retry-After")
            )
            raise ValueError(
                f"Provider returned HTTP {response.status_code}; cooldown applied"
            )
        body = response.json()
        raw = (
            body["message"]["content"]
            if provider == "ollama"
            else body["choices"][0]["message"]["content"]
        )
        return parse_react(self.redact(sid, raw)), body.get("model") or model

    async def next(self, sid, task, rules, fallback, emit):
        s = self.session(sid)
        if task["mode"] == "live" and not s["offline"]:
            for name in [*PROVIDERS, "ollama"]:
                if name == "ollama" and not s["ollama"]:
                    continue
                if name != "ollama" and name not in s["keys"]:
                    continue
                if s["cooldowns"].get(name, 0) > time.time():
                    continue
                try:
                    proposal, model = await self.request(
                        sid, name, task["messages"], rules, task["seed"]
                    )
                    return proposal, "Live", name, model
                except (ValueError, KeyError, TypeError, TimeoutError, httpx.HTTPError):
                    s["cooldowns"][name] = max(
                        s["cooldowns"].get(name, 0), time.time() + 15
                    )
                    emit(
                        "provider",
                        {
                            "provider": name,
                            "status": "unavailable, invalid output, or budget exhausted; advancing chain with existing conversation",
                        },
                    )
        if task["mode"] in ("live", "replay"):
            for path in sorted((ROOT / "recordings").glob("*.json")):
                try:
                    recording = json.loads(path.read_text())
                    if recording.get("genuine") is not True:
                        continue
                    for turn in recording["turns"]:
                        if turn["checkpoint"] == checkpoint(task, rules):
                            return (
                                Proposal.model_validate(turn["proposal"]),
                                "Replay",
                                recording["provider"],
                                recording["model"],
                            )
                except (ValueError, KeyError, TypeError):
                    continue
            emit(
                "provider",
                {
                    "status": "No compatible genuine replay checkpoint. Scripted fallback; recorded restart is available only when genuine recordings are installed."
                },
            )
        return fallback(), "Scripted", "scripted", "fixture-1.2"


def checkpoint(task, rules):
    return digest(
        {
            "messages": task["messages"],
            "executed": task["executed"],
            "config": rules,
            "fixture": task["fixture_version"],
        }
    )
