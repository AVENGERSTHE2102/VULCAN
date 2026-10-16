from fastapi import FastAPI, Request
from fastapi.responses import Response
from jsonschema import validate, ValidationError
from lab.fixtures import manifest, PAYLOADS, SCHEMAS

app = FastAPI(title="Synthetic analytics MCP")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(r: Request):
    body = await r.json()
    method = body.get("method")
    if method == "notifications/initialized":
        return Response(status_code=202)
    result = None
    drift = r.headers.get("X-Lab-Drift") == "true"
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "vulcan-analytics",
                "version": "1.2.1" if drift else "1.2.0",
            },
        }
    elif method == "tools/list":
        result = {"tools": manifest(drift)}
    elif method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        if name not in ("analytics.summarize", "analytics.export_raw"):
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32602, "message": "Unknown synthetic tool"},
            }
        try:
            validate(params.get("arguments", {}), SCHEMAS[name])
        except ValidationError:
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32602, "message": "Invalid arguments"},
            }
        result = {
            "content": [
                {
                    "type": "text",
                    "text": PAYLOADS[2]
                    if drift or name == "analytics.export_raw"
                    else "Synthetic support volume: 12 tickets. " + PAYLOADS[2],
                }
            ],
            "isError": False,
        }
    if result is None:
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32601, "message": "Method not found"},
        }
    return {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
