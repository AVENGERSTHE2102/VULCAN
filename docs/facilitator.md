# Solo or optional workshop flow

| Minutes | Activity |
|---|---|
| 0–10 | Read safety copy; inspect trust boundaries in Recon. |
| 10–30 | M1 goal hijack and M2 persistent memory poisoning. |
| 30–55 | M3 tool output and M4 direct privilege probes. |
| 55–80 | M5 transformed-data exfiltration and M6 sandbox inspection. |
| 80–95 | M7 rogue MCP update and revocation. |
| 95–110 | Final Boss timeline reconstruction and containment. |
| 110–115 | Evidence review, self-assessment, closing. |

Use Facilitator's optional timer, checklist, and locally generated QR. Localhost QR links work on the same machine only. There is no classroom network service or account provisioning.

Before each mission, select Vulnerable, run it, and retain the trace. Apply Hardened and rerun without deleting the baseline evidence. Pin at least the attack proposal and the denial. Check the tool result proving the authorized task succeeded, then write the failed boundary, containment, and synthetic impact in the worksheet. Save notes before switching missions.

M2 needs two tasks: first persist the poisoned note, then use Run task 2. Apply hardened controls and repeat task 2 to see quarantine prevent retrieval. Reset clears its memory; do not reset between the two poisoning tasks.

Scores are 30 for a vulnerable impact, 40 for a hardened denial plus legitimate success (M6 instead verifies limits), 20 for two pinned evidence events, and 0–10 manual assessment. Suggested manual rubric: 0–2 for identifying the source, 0–3 for explaining the boundary, 0–3 for a supported retest, and 0–2 for explaining impact. This is self-assessment, not an external certification. Live release calibration is separate from these scores.

For offline workshops, use Scripted. Explain that these are demonstrations of actual execution gates with deterministic proposals, not measurements of a language model. If a genuine recording is available, its Replay label and original planner provenance stay visible. Keep a backup planner key outside the repo in a password manager; enter it only through Settings when needed. Global reset and API restart erase memory-only keys.

Working closing: **Observe the attack. Trace the boundary. Apply the control. Prove the legitimate workflow still works.**


## Open prompt experiments

In Missions, edit the trusted task and untrusted content. The prefilled text is just an example. Editing either field switches the run to Live mode and keeps the selected mission execution gates in place. Custom prompts never invoke the canned proposal sequence; if no live planner responds, the task pauses with its context intact. Configure a planner and resume it, or reset the mission. Learners should use synthetic text only because Live sends their custom text to the selected provider.

Field ranks and badges are calculated from observed baseline impact, hardened retests, and pinned evidence. XP excludes manual self-assessment; ranks do not lock missions.
