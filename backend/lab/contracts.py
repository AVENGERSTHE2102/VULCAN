from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextSegment(StrictModel):
    id: str
    trust: Literal["trusted", "untrusted", "tool", "memory"]
    provenance: str
    tags: list[str] = []
    text: str


class Proposal(StrictModel):
    thought: str = Field(default="", max_length=3000)
    tool: str = Field(max_length=80)
    arguments: dict[str, Any] = {}


class Decision(StrictModel):
    verdict: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]
    reason: str
    control: str


class ToolResult(StrictModel):
    status: int
    data: Any
    provenance: str = "synthetic-lab"
    tags: list[str] = []


class AuditEvent(StrictModel):
    id: str
    task_id: str
    action_id: str | None = None
    sequence: int
    timestamp: float
    kind: str
    source: Literal["Live", "Replay", "Scripted", "System"]
    provider: str | None = None
    model: str | None = None
    data: Any
