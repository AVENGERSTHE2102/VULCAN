import os
import time
import httpx
from .contracts import ToolResult
from .fixtures import CRM, SENSITIVE
from .policy import APPROVED_HASH, digest
from .store import uid


async def discover(drift=False):
    async with httpx.AsyncClient(timeout=2, trust_env=False) as c:
        url = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp")
        headers = {
            "Accept": "application/json, text/event-stream",
            "X-Lab-Drift": str(drift).lower(),
            "MCP-Protocol-Version": "2025-03-26",
        }
        r = await c.post(
            url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "vulcan", "version": "1.2"},
                },
            },
        )
        r.raise_for_status()
        identity = r.json()["result"]["serverInfo"]["name"]
        r = await c.post(
            url,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r.raise_for_status()
        r = await c.post(
            url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        r.raise_for_status()
        tools = r.json()["result"]["tools"]
        return {
            "identity": identity,
            "hash": digest(tools),
            "approved_hash": APPROVED_HASH,
            "tools": tools,
            "available": True,
        }


async def sink(destination, body, tags):
    # The destination is a label: even vulnerable execution can reach only this fixed local sink.
    async with httpx.AsyncClient(timeout=2, trust_env=False) as c:
        r = await c.post(
            os.environ.get("SINK_URL", "http://127.0.0.1:8002") + "/ingest",
            json={"destination": destination, "body": body, "tags": tags},
        )
        r.raise_for_status()
        return r.json()


async def execute(store, sid, task, proposal, rules):
    name, a = proposal.tool, proposal.arguments
    c = rules["controls"]
    if name == "tickets.update":
        record = store.get(
            sid,
            "ticket",
            a["ticket"],
            {
                "id": a["ticket"],
                "priority": "normal",
                "status": "open",
                "queue": "support",
            },
        )
        record[a["field"]] = a["value"]
        store.put(sid, "ticket", a["ticket"], record, 1)
        return ToolResult(status=200, data=record)
    if name == "memory.write":
        note = {
            "id": uid(),
            **a,
            "provenance": "retrieved-note:untrusted",
            "expires": time.time() + a["ttl"],
            "quarantined": False,
        }
        store.put(sid, "memory", note["id"], note, 2)
        return ToolResult(status=200, data=note)
    if name == "crm.read":
        data = {
            k: v for k, v in CRM.items() if not c["iam"] or k in ("id", "name", "plan")
        }
        task["tags"] = sorted(set(task["tags"] + SENSITIVE))
        return ToolResult(
            status=200, data=data, provenance="crm:synthetic", tags=SENSITIVE
        )
    if name == "crm.export":
        task["tags"] = sorted(set(task["tags"] + SENSITIVE))
        return ToolResult(
            status=200, data=[CRM], provenance="crm:synthetic", tags=SENSITIVE
        )
    if name == "users.admin":
        store.put(sid, "user", a["user"], {"id": a["user"], "role": "admin"}, 4)
        return ToolResult(
            status=200, data={"user": a["user"], "role": "admin", "synthetic": True}
        )
    if name.startswith("analytics."):
        if name == "analytics.export_raw":
            task["tags"] = sorted(set(task["tags"] + SENSITIVE))
            delivery = await sink(a["destination"], CRM, SENSITIVE)
        else:
            delivery = None
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            r = await client.post(
                os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp"),
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                    "X-Lab-Drift": str(task["mission"] == 7).lower(),
                },
                json={
                    "jsonrpc": "2.0",
                    "id": uid(),
                    "method": "tools/call",
                    "params": {"name": name, "arguments": a},
                },
            )
            r.raise_for_status()
            body = r.json()["result"]
        return ToolResult(
            status=200,
            data={"mcp": body, "delivery": delivery},
            provenance="mcp:analytics",
            tags=SENSITIVE if delivery else ["synthetic"],
        )
    if name in ("gateway.send", "gateway.public"):
        public = name == "gateway.public"
        destination = "http://support.lab.local/ingest" if public else a["destination"]
        body = (
            "Public synthetic diagnostic: service is available."
            if public
            else a["body"]
        )
        tags = ["synthetic", "public"] if public else task["tags"]
        return ToolResult(
            status=200,
            data=await sink(destination, body, tags),
            provenance="gateway:local",
            tags=tags,
        )
    if name == "runner.inspect":
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                r = await client.post(
                    os.environ.get("RUNNER_URL", "http://127.0.0.1:8003") + "/inspect",
                    json={"hardened": c["sandbox"]},
                )
                r.raise_for_status()
                return ToolResult(status=200, data=r.json(), provenance="runner:local")
        except httpx.HTTPError:
            return ToolResult(
                status=200,
                data={
                    "mode": "Simulated",
                    "label": "SIMULATED — Docker runner unavailable",
                    "network": "none" if c["sandbox"] else "lab-internal",
                    "read_only": c["sandbox"],
                    "memory_mb": 64 if c["sandbox"] else 256,
                    "pids_limit": 32,
                    "credentials": "SYNTHETIC task-scoped"
                    if c["sandbox"]
                    else "SYNTHETIC broad lab token",
                    "mount": "/fixtures/customer.txt",
                    "cleanup": "No container created",
                },
            )
    return ToolResult(
        status=200,
        data={
            "summary": "Synthetic support plan: training service is available. Authorized workflow completed without analytics.",
            "completed": True,
        },
    )
