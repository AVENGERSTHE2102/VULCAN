# Verification record — 2026-10-17

Environment: macOS, Python 3.13.5 via uv, Node 24.7.0, Docker CLI 29.4.0. Docker daemon was not running. No hosted provider keys were supplied or read from the environment.

- `uv run pytest -q`: 38 passing tests. All seven missions exercise both vulnerable impact and hardened legitimate success through the real shared execution gates. MCP/sink ASGI services run in-process in these tests.
- Tests cover bounded ReAct parsing, unknown/invalid proposals, credential redaction (including validation errors and JSON escapes), configuration last-valid reload, provider adapter wire contracts, failover with unchanged conversation and no repeated side effects, bounded Retry-After, budget rejection, paused/rechecked approvals, memory quarantine/TTL across tasks, IAM/expiry, drift/revocation, encoding/summary/truncation egress, runner cleanup including cancellation, reset/session isolation, exact-checkpoint replay and incompatible fallback, incident containment without historical deletion, and all-mission offline execution with external sockets rejected.
- `npm run build`: TypeScript strict check and Vite production bundle pass. Assets are bundled; no CDN is required. `npm install` reported zero audited dependency vulnerabilities at installation time.
- `uv run python scripts/contracts.py --check`: generated API/UI contracts match.
- `docker compose config --quiet` and the offline overlay configuration: valid.
- `uv run python scripts/retest.py`: all 14 vulnerable/hardened runs passed over actual local HTTP API + MCP + fake-sink services, not mocked HTTP. No hosted requests were made. Runner was explicitly Simulated. Observed mission reset latency: 0.001–0.006 seconds. This is a local development measurement, not Docker acceptance.
- Manual browser smoke test in Chrome: dashboard loads; Mission 1 vulnerable run changes T-1043/T-1044; hardened retest displays DENY/403 for both and still updates T-1042 priority to high. Trace source stays Scripted and the score reflects baseline + legitimate hardened retest.
- `git diff --check`: clean.

One upstream warning remains: FastAPI/Starlette's TestClient announces deprecation of its httpx transport in favor of httpx2. The pinned test stack works; do not change the transport dependency without testing compatibility.

Not verified: hosted BYOK success/quotas, local model suitability, 20-trial live metrics, genuine recordings, replay UI with installed genuine recordings, real Docker task execution, prepared-image Compose startup timing, physical network-disabled Compose operation, and mobile-device rendering. See release-status.md for the open gates. Scripted tests and mocked adapter tests do not count as live model calibration.
