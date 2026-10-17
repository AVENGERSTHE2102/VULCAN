# Release status

This implementation is a usable keyless learning lab, **not a calibrated live-provider release**.

Implemented: seven mission execution paths, local MCP protocol discovery/calls, fake sinks, shared gates, scoped synthetic IAM, memory quarantine, provider chain and session BYOK, approval pause/recheck, exact-checkpoint replay, labeled scripted/simulated fallback, dashboard, evidence, exports, score rules, final incident simulation, configuration snapshots, Compose and offline overlay.

Verification is recorded in `verification.md`. These release gates remain open:

- Hosted BYOK execution and model suitability: no key was supplied during implementation.
- For each selected provider/model: 20 vulnerable trials, at least 70% attack success; 20 hardened trials, at least 90% legitimate-task success, with deterministic malicious-proposal containment independently checked.
- Three to five genuine successful Live recordings per mission. No scripted trace is presented as a genuine recording.
- Final Boss derived from a genuine recorded attack chain. The keyless version explicitly labels its causal chain provisional Scripted and noise synthetic.
- Real Docker runner, prepared-image startup under two minutes, and physical network-disabled Compose acceptance: Docker CLI is available, but the daemon was stopped.
- Original exact PRD copy: omitted by the handoff; user accepted proceeding with documented working copy.

## Calibrate locally

1. Run the lab with local internal services. Configure only one selected hosted provider key in Settings; test it. Disable Offline and Ollama.
2. Set an intentional session request/token budget in Config (up to 1,000 requests / 1,000,000 reserved tokens). Calibration makes paid provider requests; set your provider-side spend limit too.
3. Find this local lab's `vulcan_session` cookie in browser developer tools. The script reads it using a hidden prompt, never an argument or file. This cookie controls your local lab session; do not share it.
4. Run one mission at a time:

   ```sh
   uv run python scripts/calibrate.py --mission 1 --provider groq
   ```

5. Inspect `artifacts/calibration/m1-summary.json` and exported Live transcripts. The script refuses mixed/fallback trials, preserves exact checkpoint and per-turn provenance, exports up to five successful vulnerable recordings, and restores the original session policy. It resets that mission between trials, so export previous learning evidence before calibration. Global reset clears keys/budgets when preparing a fresh calibration session.
6. Repeat for all seven missions and selected models. Copy reviewed genuine recordings to recordings/ (the Docker image packages them on the next build). Logs exposes explicit recorded restart. Re-run containment with those proposals under hardened rules. Generate Final Boss after a genuine attack run in the session, or use a shipped recording chain after rebuilding.

A policy/model/fixture change invalidates the corresponding calibration. The Groq default is `openai/gpt-oss-20b` (Groq retired the prior `llama-3.1-8b-instant` default for standard developer access); optional local candidate is `qwen2.5:3b`. Neither has been advertised as calibrated or free.
