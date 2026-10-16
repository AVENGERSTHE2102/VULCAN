# Offline preparation

While network is available and Docker is running:

```sh
make install
make prepare
make up
```

`make prepare` builds API/dashboard/runner/task images, initializes the synthetic fixture volume, and downloads the optional Ollama service image. If using local planning, start the Ollama profile and pull `qwen2.5:3b` before disconnecting. CPU/memory requirements and actual model suitability need measurement on your machine.

Select Offline in Settings for deterministic Scripted/compatible Replay operation. This disables all planner requests, including Ollama. For a physically isolated API network:

```sh
make offline
```

The offline override removes the API's planner network. It uses existing images only (`--no-build --pull never`); external downloads during startup are not allowed. The dashboard has no CDN assets, remote fonts, remote QR service, or external scripts. Tools still reach the internal lab MCP, sinks, and runner. Local tools never resolve the displayed fake collector hostname.

For local-model offline planning, keep Settings Offline off, enable Ollama, and use the isolated Compose overlay with a previously loaded Ollama profile. The API can reach Ollama over the lab network but not hosted providers. Remove hosted keys to avoid their bounded timeout attempts.

For development without Docker, run the three dev commands in README. The runner is Simulated in this mode. Offline unit/integration checks prohibit external socket connections and run all seven missions with in-process local MCP/sink ASGI services. This is not a substitute for the pending physical Docker offline acceptance run.

Acceptance measurements to record on the target machine: prepared-image startup <120 s, reset <10 s, all seven vulnerable and hardened outcomes, source labels, no externally routed planner traffic. Docker daemon absence in the implementation environment prevented measuring the prepared-image startup and real runner.

Do not use `docker compose down -v` unless discarding all synthetic installation state is intended. Dashboard Global reset affects only the current local session and clears its in-memory keys.
