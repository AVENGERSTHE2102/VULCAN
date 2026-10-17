import asyncio
import json
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
import httpx
from .contracts import Proposal
from .fixtures import SCHEMAS
from .policy import ROOT, digest

PROVIDERS = {
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-4.1-mini"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-20b"),
    "openrouter": (
        "https://openrouter.ai/api/v1/chat/completions",
        "meta-llama/llama-3.1-8b-instruct",
    ),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "mistral-small-latest"),
}

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string", "enum": list(SCHEMAS)},
        "arguments": {"type": "string"},
    },
    "required": ["thought", "tool", "arguments"],
    "additionalProperties": False,
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
    if not isinstance(data, dict):
        raise ValueError("Planner proposal must be a JSON object")
    if isinstance(data.get("arguments"), str):
        arguments = json.loads(data["arguments"])
        if not isinstance(arguments, dict):
            raise ValueError("Proposal arguments must decode to a JSON object")
        data["arguments"] = arguments
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

    async def request(self, sid, provider, messages, rules, seed=7, _format_retry=False):
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
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": 1200,
                }
                if provider == "mistral":
                    payload["random_seed"] = seed
                elif provider not in ("openai",):
                    payload["seed"] = seed
                if provider in ("groq", "openai"):
                    groq_messages = messages
                    payload["response_format"] = (
                        {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "vulcan_proposal",
                                "strict": True,
                                "schema": PROPOSAL_SCHEMA,
                            },
                        }
                        if provider == "openai"
                        or model in {
                            "openai/gpt-oss-20b",
                            "openai/gpt-oss-120b",
                            "qwen/qwen3.8-27b",
                        }
                        else {"type": "json_object"}
                    )
                    if payload["response_format"]["type"] == "json_schema":
                        groq_messages = [dict(message) for message in messages]
                        instruction = (
                            'Provider format: encode the arguments object as a JSON string, '
                            'for example "arguments":"{\\"summary\\":\\"ok\\"}".'
                        )
                        system = next(
                            (i for i, message in enumerate(groq_messages) if message["role"] == "system"),
                            None,
                        )
                        if system is None:
                            groq_messages.insert(0, {"role": "system", "content": instruction})
                        else:
                            groq_messages[system]["content"] += "\n" + instruction
                        payload["messages"] = groq_messages
                response = await client.post(
                    PROVIDERS[provider][0],
                    headers={"Authorization": "Bearer " + s["keys"][provider]},
                    json=payload,
                )
        if response.status_code >= 400:
            s["cooldowns"][provider] = time.time() + retry_delay(
                response.headers.get("Retry-After")
            )
            try:
                detail = response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            detail = self.redact(sid, str(detail))[:240]
            raise ValueError(
                f"Provider returned HTTP {response.status_code}; cooldown applied"
                + (f": {detail}" if detail else "")
            )
        try:
            body = response.json()
        except ValueError:
            if not _format_retry:
                return await self.request(
                    sid,
                    provider,
                    [
                        *messages,
                        {
                            "role": "user",
                            "content": "The last response was not valid JSON. Return one concise JSON proposal matching the required format.",
                        },
                    ],
                    rules,
                    seed,
                    _format_retry=True,
                )
            raise ValueError("Provider returned an empty or invalid JSON response") from None
        if provider == "ollama":
            message = body.get("message", {})
            raw = message.get("content")
            finish_reason = "unknown"
        else:
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            raw = message.get("content")
            finish_reason = choice.get("finish_reason") or "unknown"
        if not isinstance(raw, str) or not raw.strip():
            refusal = message.get("refusal")
            detail = "Provider returned empty content"
            if refusal:
                detail += " (refusal)"
            elif finish_reason == "length":
                detail += " (output token limit reached)"
            else:
                detail += f" (finish reason: {finish_reason})"
            if not refusal and not _format_retry:
                return await self.request(
                    sid,
                    provider,
                    [*messages, {"role": "user", "content": "Return one concise JSON proposal matching the requested format."}],
                    rules,
                    seed,
                    _format_retry=True,
                )
            raise ValueError(detail)
        try:
            proposal = parse_react(self.redact(sid, raw))
        except ValueError:
            if _format_retry:
                raise
            return await self.request(
                sid,
                provider,
                [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "The last response did not match the required proposal format. Return one concise JSON proposal with thought, tool, and arguments only."},
                ],
                rules,
                seed,
                _format_retry=True,
            )
        return proposal, body.get("model") or model

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
                except (ValueError, KeyError, TypeError, TimeoutError, httpx.HTTPError) as exc:
                    s["cooldowns"][name] = max(
                        s["cooldowns"].get(name, 0), time.time() + 15
                    )
                    emit(
                        "provider",
                        {
                            "provider": name,
                            "status": self.redact(
                                sid,
                                str(exc) or "Provider failed; advancing with existing conversation",
                            )[:240],
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
        if task.get("freeform"):
            emit(
                "provider",
                {"status": "No compatible live planner or genuine replay. A custom prompt will pause here; no canned proposal is used."},
            )
            return None, "Unavailable", None, None
        if task["mode"] in ("live", "replay"):
            emit(
                "provider",
                {"status": "No compatible genuine replay checkpoint. Using the labeled Scripted demonstration."},
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
