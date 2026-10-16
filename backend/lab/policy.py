import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal
import yaml
from pydantic import Field
from .contracts import Decision, StrictModel

ROOT = Path(__file__).resolve().parents[2]


class Controls(StrictModel):
    task_scope: bool
    approval: bool
    memory: bool
    mcp_pinning: bool
    iam: bool
    egress: bool
    sandbox: bool


class Rules(StrictModel):
    mode: Literal["vulnerable", "hardened", "custom"]
    controls: Controls
    request_budget: int = Field(ge=1, le=1000)
    token_budget: int = Field(ge=1000, le=1000000)


def load_snapshot(name="vulnerable"):
    return Rules.model_validate(
        yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())
    ).model_dump()


def validate_config(text):
    if len(text) > 16000:
        raise ValueError("Configuration is too large")
    return Rules.model_validate(yaml.safe_load(text)).model_dump()


class Config:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("LAB_CONFIG", ".data/active.yaml"))
        self.rules = load_snapshot(
            os.environ.get("LAB_START_MODE")
            or (
                (ROOT / ".default-mode").read_text().strip()
                if (ROOT / ".default-mode").exists()
                else "vulnerable"
            )
        )
        self.signature = None
        self.error = None
        self.reload()

    def reload(self):
        if self.path.exists():
            raw = self.path.read_text()
            signature = hashlib.sha256(raw.encode()).hexdigest()
            if signature != self.signature:
                try:
                    self.rules = validate_config(raw)
                    self.error = None
                except (ValueError, yaml.YAMLError):
                    self.error = "Invalid configuration: retained last valid rules"
                self.signature = signature
        return self.rules

    def save(self, raw):
        rules = validate_config(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(yaml.safe_dump(rules))
        os.replace(temp, self.path)
        self.reload()
        return rules


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


APPROVED_HASH = digest(json.loads((ROOT / "fixtures/mcp/approved.json").read_text()))


def evaluate(
    proposal,
    task,
    rules,
    *,
    approval=False,
    manifest_hash=APPROVED_HASH,
    identity="vulcan-analytics",
    revoked=False,
):
    c, name, a = rules["controls"], proposal.tool, proposal.arguments

    def deny(reason, control):
        return Decision(verdict="DENY", reason=reason, control=control)

    if name.startswith("analytics.") and (
        revoked
        or (
            c["mcp_pinning"]
            and (manifest_hash != APPROVED_HASH or identity != "vulcan-analytics")
        )
    ):
        return deny(
            "MCP identity, schema or description differs from approved manifest, or server is revoked",
            "mcp_pinning",
        )
    if (
        c["task_scope"]
        and name == "tickets.update"
        and (
            a["ticket"] != "T-1042" or a["field"] != "priority" or a["value"] != "high"
        )
    ):
        return deny(
            "Ticket text cannot authorize changes outside T-1042 priority", "task_scope"
        )
    scope = {
        "tickets.update": "ticket:" + a.get("ticket", "") + ":" + a.get("field", ""),
        "crm.read": "crm.read",
        "crm.export": "crm.export",
        "users.admin": "users.admin",
        "memory.write": "memory.write",
        "analytics.summarize": "analytics.read",
        "analytics.export_raw": "analytics.export",
        "gateway.send": "gateway.send",
        "gateway.public": "gateway.public",
        "runner.inspect": "runner.inspect",
        "support.summary": "support.read",
        "finish": "support.read",
    }.get(name)
    if c["iam"] and (
        scope not in task["token"].get("scopes", [])
        or task["token"]["expires"] <= time.time()
    ):
        return deny("403: task token lacks scope or has expired", "iam")
    if (
        c["memory"]
        and name == "memory.write"
        and (a["type"] != "fact" or task["untrusted_seen"])
    ):
        return deny(
            "Untrusted instructions are quarantined; only approved facts may persist",
            "memory",
        )
    if c["egress"] and name in ("gateway.send", "analytics.export_raw"):
        if a["destination"] != "http://support.lab.local/ingest":
            return deny("Destination is outside the lab support allowlist", "egress")
        if "sensitive" in task["tags"]:
            return deny(
                "Sensitive provenance survives summaries, truncation and encoding",
                "egress",
            )
    if (
        c["approval"]
        and name in ("memory.write", "users.admin", "crm.export")
        and not approval
    ):
        return Decision(
            verdict="REQUIRE_APPROVAL",
            reason="Explicit learner approval required; no automatic execution",
            control="approval",
        )
    return Decision(
        verdict="ALLOW", reason="Passed active execution gates", control="execution"
    )
