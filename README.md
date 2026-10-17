# VULCAN 1.2 · Solo Learning Lab

VULCAN is a local, synthetic learning lab for prompt injection and agent containment. Explore seven missions, write your own attack prompts, inspect the agent’s proposals, and verify which controls allow or block each action. All business records and tool effects are synthetic.

## Run with Docker

The same Docker Compose setup works on macOS, Windows, and Linux. No API key is needed to start or use the labeled Scripted examples.

### 1. Install prerequisites

- **macOS and Windows:** Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/). On Windows, use the default Linux-container mode.
- **Linux:** Install Docker Engine and the Docker Compose v2 plugin using your distribution’s Docker instructions. Ensure your user can run `docker` commands.
- Install **Git** if it is not already available.

Check that Docker is running:

```sh
docker --version
docker compose version
docker info
```

### 2. Download the project

Open Terminal on macOS/Linux or PowerShell on Windows, then run:

```sh
git clone https://github.com/AVENGERSTHE2102/VULCAN.git
cd VULCAN
```

### 3. Build and start the lab

The first command builds a small isolated synthetic-fixture image and initializes its volume. The second builds and starts the dashboard and lab services:

```sh
docker compose --profile prepare build task-image
docker compose --profile prepare run --rm task-image
docker compose up -d --build
```

The initial build downloads base images and packages, so it needs an internet connection, several gigabytes of free disk space, and may take a few minutes. When containers are healthy, open **[http://localhost:8080](http://localhost:8080)**. The dashboard is bound to your local machine; the lab’s API, tools, runner, and synthetic sinks are not published as host ports.

On macOS/Linux, `make up` runs these same three commands if `make` is installed.

### 4. Try a mission

Start with the Scripted examples to see a complete trace without a provider account. Open a mission, enter or edit the trusted task and untrusted content, run it, then inspect the proposal, policy decision, and synthetic result. Harden the mission and run it again to compare outcomes.

For custom prompts that need a real model, open **Settings** in the dashboard and add your own provider key there. VULCAN keeps keys in server memory, does not return them to the browser, and clears them when the API restarts. Live requests send synthetic lab context and model output to the provider you select. Never enter real customer data or production credentials.

### Stop, restart, and reset

Stop the containers while keeping your local progress and settings data:

```sh
docker compose down
```

Start them again later:

```sh
docker compose up -d
```

Use the dashboard’s reset controls to reset a mission or the whole lab. To erase all Compose-stored lab progress and prepared fixture data, run:

```sh
docker compose down --volumes
```

This permanently removes the lab database, active configuration, fixture volume, and any optional Ollama model data.

### Optional local Ollama model

Ollama is not required. To run the optional local model service and fetch the suggested model:

```sh
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5:3b
```

Then select Ollama in Settings. The first model download can be several gigabytes.

## Troubleshooting

- **Docker cannot connect to its daemon:** Start Docker Desktop, or start the Docker service on Linux, then retry `docker info`.
- **Build or install reports “no space left on device”:** Free several gigabytes on the host, then retry. Docker images and frontend packages both use local disk space.
- **Port 8080 is already in use:** Stop the other service using it, then run `docker compose up -d --build` again. The dashboard currently uses `127.0.0.1:8080`.
- **The dashboard does not load immediately:** Check startup with `docker compose ps`; wait for services to become healthy, then refresh the page. View diagnostics with `docker compose logs --tail=100`.
- **A Live provider test fails:** Confirm the key and model access in Settings. Scripted examples remain available without a key.

## Run without Docker (Python + Node)

This starts the Python API and the Vite dashboard together. Install Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ (includes npm), and Git first; allow several gigabytes of free disk space for the frontend dependencies. From a terminal, this one-line command clones the project, installs its locked dependencies, and starts both servers:

```sh
git clone https://github.com/AVENGERSTHE2102/VULCAN.git && cd VULCAN && python3 scripts/dev.py
```

On Windows PowerShell, use:

```powershell
git clone https://github.com/AVENGERSTHE2102/VULCAN.git; if ($?) { cd VULCAN; python scripts/dev.py }
```

Open **[http://localhost:5173](http://localhost:5173)**. Keep that terminal open; press **Ctrl+C** to stop both servers. For later runs from the project folder, use `python3 scripts/dev.py` (macOS/Linux) or `python scripts/dev.py` (Windows). Internal MCP and sink services are optional (`make dev-services`); without the runner service, inspection is explicitly simulated.

Run checks with `make check`; run the mission test subset with `make retest`.

## Project guides

- [Architecture](docs/architecture.md)
- [Mission guide](docs/missions.md)
- [Offline preparation](docs/offline.md)
- [Facilitator flow](docs/facilitator.md)
- [Release status](docs/release-status.md)

Use synthetic data only. Run one API worker. See the [release status](docs/release-status.md) for calibration limits and current readiness.
