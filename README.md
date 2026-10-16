# VULCAN 1.2 · Solo Learning Lab

A local synthetic lab for agent prompt injection and containment. Seven missions connect attacker-controlled context to observable proposals, controls, and legitimate outcomes.

```sh
make up       # prepared Docker images: dashboard http://localhost:8080
```

No key required: traces use an explicit **Scripted** label. Enter an optional planner key in Settings for **Live** runs. Optional Ollama: `docker compose --profile ollama up -d`, then `docker compose exec ollama ollama pull qwen2.5:3b`.

For development without Docker:

```sh
make install
make dev-api  # terminal 1, localhost:8000
make dev-web  # terminal 2, localhost:5173
```

Internal MCP and sink services: `make dev-services`. Without the runner service the inspection is explicitly simulated.

```sh
make check
make retest
make down
```

See [architecture](docs/architecture.md), [mission guide](docs/missions.md), [offline preparation](docs/offline.md), [facilitator flow](docs/facilitator.md), and [release status](docs/release-status.md). Run one API worker. Keys are memory-only; use synthetic data throughout.

Run `uv run python scripts/retest.py` against the development API for a fresh-session HTTP acceptance run (all seven missions, both snapshots). Existing-session CLI reset: `uv run python scripts/reset.py --mission 1` or `--all` reads the local browser session cookie via hidden stdin. Dashboard reset buttons are simpler for normal use.

Distribution branches are created with `make branches` after committing verification. `vulnerable` starts with controls off; `known-good` starts hardened. Existing session policy and active YAML still take precedence; use a fresh session/global reset when comparing branch defaults. Neither branch implies that pending hosted-calibration release gates have passed.
