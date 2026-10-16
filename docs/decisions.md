# Implementation decisions

- One learner, one local installation. Session cookies partition task data, budgets, keys, memory, evidence, and resets. No accounts or hosted classroom system.
- Only the dashboard publishes a localhost port. API, MCP, sink, and runner are internal services. Hosted planners are the sole optional external requests made by the API.
- The handoff omitted the original specification and proposed directory tree. The user accepted proceeding. PRD.md records that gap; backend/, frontend/, services/, config/, fixtures/, recordings/, scripts/, docs/ are the adopted structure.
- SQLite persists synthetic state and audit events; provider credentials stay only in process memory and disappear on restart/global reset. One API worker is required.
- Canonical decisions are ALLOW, DENY, REQUIRE_APPROVAL. Approval resumes explicitly and rechecks current policy. Rejected proposals still allow the authorized task to continue.
- A model's Thought field is unverified model-generated text. Attribution is explanatory only. Labels follow every event through export.
- Scripted demonstrations are deterministic synthetic proposals, never real recordings. Replay accepts only genuine live transcripts whose exact conversation/action/config checkpoint matches. Incompatible replay requires an explicit restart.
- The Docker runner accepts a fixed inspection task only, never a command, path, image, URL, or credential chosen by a model. Its Docker socket is available only to the runner; containers have synthetic mounts and credentials. Missing Docker produces a visibly labeled simulation.
- The optional 115-minute flow remains usable for solo study. Scores measure evidence and actual retest events; manual rubric fields are self-assessment.
- No hosted calibration or genuine recordings can be fabricated. Release gates remain pending until locally entered BYOK enables measured trials. Model names are initial candidates, not availability guarantees.
