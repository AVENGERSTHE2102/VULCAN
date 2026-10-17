import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import QRCode from "qrcode";
import { api, download } from "./api";
import type {
  AuditEvent,
  ContextSegment,
  Proposal,
  Decision,
  ToolResult,
} from "./contracts";
import "./style.css";

type Rules = {
  mode: string;
  controls: Record<string, boolean>;
  request_budget: number;
  token_budget: number;
};
type Settings = {
  providers: {
    name: string;
    configured: boolean;
    model: string;
    cooldown_seconds: number;
  }[];
  offline: boolean;
  ollama: boolean;
  requests: number;
  tokens_reserved: number;
  quota_hint: string;
  privacy: string;
};
type Mission = {
  id: number;
  title: string;
  request: string;
  payload: string;
  control: string;
  kind: string;
  hints: string[];
};
type Task = {
  id: string;
  mission: number;
  status: string;
  source: string;
  provider?: string;
  model?: string;
  legitimate_success: boolean;
  attack_success: boolean;
  created: number;
  freeform?: boolean;
};
type Sheet = {
  observation: string;
  boundary: string;
  control: string;
  retest: string;
  impact: string;
  pins: string[];
  manual: number;
};
type Score = {
  mission: number;
  title: string;
  baseline: boolean;
  hardened_retest: boolean;
  evidence: boolean;
  automatic: number;
  manual: number;
};
type Incident = {
  label: string;
  events: AuditEvent[];
  containment: Record<string, boolean>;
  actions: { id: string; tool: string; verdict: string; source: string }[];
};
const emptySheet: Sheet = {
  observation: "",
  boundary: "",
  control: "",
  retest: "",
  impact: "",
  pins: [],
  manual: 0,
};
const pages = [
  "Home",
  "Recon",
  "Missions",
  "Final Boss",
  "Logs",
  "Config",
  "Scoreboard",
  "Settings",
  "Facilitator",
];
const subtitle: Record<string, string> = {
  Home: "YOUR LOCAL CONTAINMENT LAB",
  Recon: "MAP THE ATTACK SURFACE",
  Missions: "OBSERVE · CONTAIN · PROVE",
  "Final Boss": "INCIDENT RESPONSE EXERCISE",
  Logs: "FOLLOW THE EVIDENCE",
  Config: "BOUNDARIES AS CODE",
  Scoreboard: "MEASURE WHAT YOU PROVED",
  Settings: "PLANNERS & PRIVACY",
  Facilitator: "A GUIDED 115-MINUTE LAB",
};
function Glyph({ n = 0 }: { n?: number }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
    >
      {n % 3 === 0 ? (
        <>
          <path d="m12 3 9 5v8l-9 5-9-5V8z" />
          <path d="m3 8 9 5 9-5M12 13v8" />
        </>
      ) : n % 3 === 1 ? (
        <>
          <circle cx="10" cy="10" r="6" />
          <path d="m15 15 6 6M7 10h6M10 7v6" />
        </>
      ) : (
        <>
          <path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h4" />
        </>
      )}
    </svg>
  );
}
function Chip({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={"chip " + tone}>{children}</span>;
}
function Panel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={"shell " + className}>
      <div className="core">{children}</div>
    </section>
  );
}
function App() {
  const initial = new URLSearchParams(location.search);
  const [page, setPage] = useState(
    pages.includes(initial.get("view") || "") ? initial.get("view")! : "Home",
  );
  const [mission, setMission] = useState(
    Math.max(1, Math.min(7, Number(initial.get("mission")) || 1)),
  );
  const [missions, setMissions] = useState<Mission[]>([]);
  const [settings, setSettings] = useState<Settings>();
  const [rules, setRules] = useState<Rules>();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task>();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [sheet, setSheet] = useState<Sheet>(emptySheet);
  const [scores, setScores] = useState<Score[]>([]);
  const [recon, setRecon] = useState<unknown>();
  const [yaml, setYaml] = useState("");
  const [incident, setIncident] = useState<Incident>();
  const [recordings, setRecordings] = useState<
    { id: string; mission: number; provider: string; model: string }[]
  >([]);
  const [mode, setMode] = useState("live");
  const [promptRequest, setPromptRequest] = useState("");
  const [promptPayload, setPromptPayload] = useState("");
  const [hint, setHint] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [qr, setQr] = useState("");
  const [remaining, setRemaining] = useState(115 * 60);
  const [timer, setTimer] = useState(false);
  const stream = useRef<EventSource | null>(null);
  const m = missions.find((x) => x.id === mission);
  const customPrompt =
    !!m && (promptRequest !== m.request || promptPayload !== m.payload);
  async function refresh() {
    const [s, ts, sc] = await Promise.all([
      api<{ settings: Settings; config: Rules }>("/session"),
      api<Task[]>("/tasks"),
      api<Score[]>("/scoreboard"),
    ]);
    setSettings(s.settings);
    setRules(s.config);
    setTasks(ts);
    setScores(sc);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void act(async () => {
      setMissions(await api<Mission[]>("/missions"));
      await refresh();
    });
    return () => stream.current?.close();
  }, []);
  useEffect(() => {
    const url = new URL(location.href);
    url.searchParams.set("view", page);
    url.searchParams.set("mission", String(mission));
    history.replaceState({}, "", url);
  }, [page, mission]);
  useEffect(() => {
    if (m) {
      setPromptRequest(m.request);
      setPromptPayload(m.payload);
    }
    setHint(0);
    setSheet(emptySheet);
    void api<Sheet>("/worksheets/" + mission)
      .then(setSheet)
      .catch((e) => setMessage(e.message));
  }, [mission, missions]);
  useEffect(() => {
    void act(async () => {
      if (page === "Recon") setRecon(await api("/recon"));
      if (page === "Config")
        setYaml((await api<{ yaml: string }>("/config")).yaml);
      if (page === "Logs") setRecordings(await api("/recordings"));
      if (page === "Final Boss")
        setIncident(await api<Incident>("/final-boss"));
      if (page === "Facilitator")
        setQr(
          await QRCode.toDataURL(
            location.origin + "/?view=Missions&mission=" + mission,
            { margin: 1, width: 180 },
          ),
        );
      await refresh();
    });
  }, [page]);
  useEffect(() => {
    if (!timer) return;
    const id = setInterval(
      () =>
        setRemaining((x) => {
          if (x <= 1) {
            setTimer(false);
            return 0;
          }
          return x - 1;
        }),
      1000,
    );
    return () => clearInterval(id);
  }, [timer]);
  function watch(t: Task) {
    stream.current?.close();
    setSelected(t);
    setEvents([]);
    const es = new EventSource("/api/tasks/" + t.id + "/stream");
    stream.current = es;
    es.onmessage = (e) => {
      const event = JSON.parse(e.data) as AuditEvent;
      setEvents((old) =>
        old.some((x) => x.id === event.id) ? old : [...old, event],
      );
    };
    es.addEventListener("settled", () => {
      es.close();
      void act(async () => {
        setSelected(await api<Task>("/tasks/" + t.id));
        await refresh();
      });
    });
    es.onerror = () => {
      es.close();
      void act(async () => {
        setEvents(await api<AuditEvent[]>("/tasks/" + t.id + "/events"));
        setSelected(await api<Task>("/tasks/" + t.id));
        await refresh();
      });
    };
  }
  async function run(followup = false) {
    if (customPrompt && !promptRequest.trim()) {
      setMessage("Write the authorized task before running this experiment.");
      return;
    }
    await act(async () => {
      const t = await api<Task>("/missions/" + mission + "/run", "POST", {
        mode: customPrompt ? "live" : mode,
        followup,
        ...(customPrompt
          ? { request: promptRequest, payload: promptPayload }
          : {}),
      });
      watch(t);
      await refresh();
    });
  }
  async function snapshot(name: string) {
    await act(async () => {
      setRules((await api<{ rules: Rules }>("/config/" + name, "POST")).rules);
      setMessage(name + " controls applied. Rerun to produce new evidence.");
      if (page === "Config")
        setYaml((await api<{ yaml: string }>("/config")).yaml);
    });
  }
  async function pin(id: string) {
    await act(async () => {
      const next = {
        ...sheet,
        pins: sheet.pins.includes(id)
          ? sheet.pins.filter((x) => x !== id)
          : [...sheet.pins, id],
      };
      setSheet(await api<Sheet>("/worksheets/" + mission, "PUT", next));
      await refresh();
    });
  }
  const total = scores.reduce((n, x) => n + x.automatic + x.manual, 0);
  const xp = scores.reduce((n, x) => n + x.automatic * 10, 0);
  const ranks = [
    { name: "Trace scout", xp: 0 },
    { name: "Boundary analyst", xp: 500 },
    { name: "Containment operator", xp: 1600 },
    { name: "Incident lead", xp: 3200 },
    { name: "Vulcan investigator", xp: 5200 },
  ];
  const rank = [...ranks].reverse().find((x) => xp >= x.xp) || ranks[0];
  const nextRank = ranks[ranks.indexOf(rank) + 1];
  const badges = [
    { name: "Signal found", earned: scores.some((x) => x.baseline) },
    { name: "Boundary held", earned: scores.some((x) => x.hardened_retest) },
    { name: "Evidence pinned", earned: scores.some((x) => x.evidence) },
    {
      name: "Seven clean retests",
      earned: scores.every((x) => x.hardened_retest) && scores.length === 7,
    },
  ];
  const active = tasks.find(
    (t) => !["completed", "failed", "cancelled", "limit"].includes(t.status),
  );
  return (
    <div className="app">
      <aside className="sidebar">
        <a
          href="/?view=Home"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            setPage("Home");
          }}
        >
          <span className="brand-mark">V</span>
          <span>
            VULCAN<small>SOLO LEARNING LAB / 1.2</small>
          </span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map((p, i) => (
            <button
              className={p === page ? "nav active" : "nav"}
              key={p}
              onClick={() => setPage(p)}
            >
              <Glyph n={i} />
              {p}
              {p === "Missions" && <span className="nav-count">07</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          LOCAL ENVIRONMENT<small>One learner. Synthetic impact.</small>
          <button className="text-button" onClick={() => setPage("Settings")}>
            Planner settings ↗
          </button>
        </div>
      </aside>
      <main id="main">
        <header className="topbar">
          <div>
            <span className="mono dim">LAB / </span>
            {page}
          </div>
          <div className="row">
            <Chip tone="green">● LOCAL SANDBOX</Chip>
            <span className="mono dim">
              {settings?.offline ? "OFFLINE" : "BYOK OPTIONAL"}
            </span>
          </div>
        </header>
        <div className="workspace">
          <div className="page-head">
            <div>
              <p className="eyebrow">{subtitle[page]}</p>
              <h1>
                {page === "Home" ? (
                  <>
                    Small lab.
                    <br />
                    <span className="muted-title">Real boundaries.</span>
                  </>
                ) : page === "Missions" ? (
                  "Contain the unexpected."
                ) : (
                  page + "."
                )}
              </h1>
            </div>
            <div className="head-note">
              <span className="status-dot" />
              SYSTEM READY
              <p>
                All impact stays synthetic.
                <br />
                Every action leaves evidence.
              </p>
            </div>
          </div>
          <div className="safety">
            <Glyph n={0} />
            <p>
              <strong>SANDBOX ONLY</strong> — All identities, records,
              credentials, destinations, and attack effects in this lab are
              synthetic. Never enter real customer data or production
              credentials. Provider API keys belong only in Settings.
            </p>
          </div>
          {active && page !== "Missions" && (
            <div className="notice">
              <span>
                Mission {active.mission}:{" "}
                {active.status === "waiting_for_provider"
                  ? "custom experiment paused for a live planner"
                  : active.status}
              </span>
              <button
                onClick={() => {
                  setMission(active.mission);
                  setPage("Missions");
                  watch(active);
                }}
              >
                Open active task →
              </button>
            </div>
          )}
          {message && (
            <div className="notice" role="status">
              {message}
              <button
                aria-label="Dismiss message"
                onClick={() => setMessage("")}
              >
                ×
              </button>
            </div>
          )}
          {page === "Home" && (
            <>
              <div className="home-grid">
                <Panel className="hero-panel">
                  <p className="eyebrow amber">THE MISSION</p>
                  <h2>
                    Watch an agent
                    <br />
                    cross the line.
                    <br />
                    <em>Then move the line.</em>
                  </h2>
                  <p className="lead">
                    Seven hands-on missions. Follow an attack from untrusted
                    input to tool action, apply a control, and prove the real
                    task still works.
                  </p>
                  <button
                    className="primary"
                    onClick={() => {
                      setPage("Missions");
                      setMission(1);
                    }}
                  >
                    Enter the lab <span>↗</span>
                  </button>
                  <div className="hero-meta mono">
                    <span>07 MISSIONS</span>
                    <span>115 MIN OPTIONAL</span>
                    <span>100% SYNTHETIC</span>
                  </div>
                </Panel>
                <Panel className="boundary-panel">
                  <div className="row spread">
                    <p className="eyebrow">THE CONTAINMENT STACK</p>
                    <span className="mono dim">01—07</span>
                  </div>
                  <div className="stack">
                    {[
                      "Trusted task",
                      "Untrusted context",
                      "Model proposal",
                      "Policy boundary",
                      "Synthetic tool",
                    ].map((s, i) => (
                      <div className={"stack-line line-" + i} key={s}>
                        <span className="mono">0{i + 1}</span>
                        {s}
                        <span>{i === 3 ? "↳ ALLOW / DENY" : "↓"}</span>
                      </div>
                    ))}
                  </div>
                  <p className="caption">
                    The model proposes. Your controls decide.
                  </p>
                </Panel>
              </div>
              <Panel className="rank-panel">
                <div className="rank-track">
                  <div>
                    <p className="eyebrow">YOUR FIELD RANK</p>
                    <h2>{rank.name}</h2>
                    <p>
                      Evidence XP <strong>{xp.toLocaleString()}</strong> ·
                      earned from measured mission work
                    </p>
                  </div>
                  <div
                    className="xp-progress"
                    role="progressbar"
                    aria-label="Progress toward next field rank"
                    aria-valuenow={xp}
                    aria-valuemin={0}
                    aria-valuemax={nextRank?.xp || rank.xp}
                  >
                    {nextRank ? (
                      <>
                        <div>
                          <span>{xp.toLocaleString()} XP</span>
                          <span>
                            {nextRank.name} · {nextRank.xp.toLocaleString()} XP
                          </span>
                        </div>
                        <div className="xp-rail">
                          <span
                            style={{
                              width: `${Math.min(100, Math.max(0, ((xp - rank.xp) / (nextRank.xp - rank.xp)) * 100))}%`,
                            }}
                          />
                        </div>
                      </>
                    ) : (
                      <span>Top rank reached</span>
                    )}
                  </div>
                </div>
                <div className="badge-row">
                  {badges.map((b) => (
                    <Chip key={b.name} tone={b.earned ? "green" : ""}>
                      {b.earned ? "◆" : "◇"} {b.name}
                    </Chip>
                  ))}
                </div>
              </Panel>
              <div className="section-head">
                <h2>Your next boundary</h2>
                <span className="mono dim">
                  PROGRESS {scores.filter((s) => s.hardened_retest).length} / 7
                </span>
              </div>
              <div className="mission-list">
                {missions.map((x, i) => (
                  <button
                    className="mission-row"
                    key={x.id}
                    onClick={() => {
                      setMission(x.id);
                      setPage("Missions");
                    }}
                  >
                    <span className="mission-num">0{x.id}</span>
                    <div>
                      <h3>{x.title}</h3>
                      <p>{x.kind}</p>
                    </div>
                    <span className="mono dim">{x.control}</span>
                    <Chip tone={scores[i]?.hardened_retest ? "green" : ""}>
                      {scores[i]?.hardened_retest ? "PROVED" : "READY"}
                    </Chip>
                    <span className="arrow">↗</span>
                  </button>
                ))}
              </div>
            </>
          )}
          {page === "Missions" && (
            <>
              <div
                className="mission-tabs"
                role="group"
                aria-label="Choose mission"
              >
                {missions.map((x) => (
                  <button
                    className={x.id === mission ? "chosen" : ""}
                    key={x.id}
                    onClick={() => {
                      setMission(x.id);
                      setSelected(undefined);
                      setEvents([]);
                    }}
                  >
                    M{x.id}
                    <span>{x.title}</span>
                  </button>
                ))}
              </div>
              {m && (
                <>
                  <div className="section-head">
                    <div>
                      <p className="eyebrow">
                        MISSION 0{mission} / {m.kind.toUpperCase()}
                      </p>
                      <h2>{m.title}</h2>
                    </div>
                    <Chip tone={rules?.mode === "hardened" ? "green" : "amber"}>
                      {rules?.mode.toUpperCase()} CONTROLS
                    </Chip>
                  </div>
                  <div className="mission-grid">
                    <Panel className="prompt-panel">
                      <div className="row spread">
                        <p className="eyebrow green">YOUR EXPERIMENT</p>
                        <Chip>MISSION GATES · M{mission}</Chip>
                      </div>
                      <p className="lead">
                        {m.kind === "direct authorization probe"
                          ? "For this lab, request a sensitive action in your trusted task. The test is whether the agent identity still limits it."
                          : "Write a task, then add text from a source the agent should treat as untrusted. Edit either field to try your own prompt."}
                      </p>
                      <label className="prompt-label">
                        Authorized task <span>TRUSTED · YOU SET THE GOAL</span>
                        <textarea
                          className="prompt-input"
                          maxLength={6000}
                          value={promptRequest}
                          onChange={(e) => setPromptRequest(e.target.value)}
                          aria-label="Your authorized task"
                        />
                      </label>
                      <label className="prompt-label">
                        Untrusted content <span>DATA · NEVER AUTHORITY</span>
                        <textarea
                          className="prompt-input payload-input"
                          maxLength={6000}
                          value={promptPayload}
                          onChange={(e) => setPromptPayload(e.target.value)}
                          aria-label="Untrusted content for this prompt experiment"
                        />
                      </label>
                      <p className="prompt-source">
                        {m.kind.toUpperCase()} · MISSION {mission} BOUNDARY ·{" "}
                        {promptRequest.length + promptPayload.length}/12,000
                        CHARACTERS
                      </p>
                      {customPrompt && (
                        <div className="live-note">
                          <span className="status-dot" /> CUSTOM EXPERIMENT ·
                          LIVE MODEL REQUIRED · NO CANNED PROPOSAL
                        </div>
                      )}
                      <div className="payload-example">
                        <span className="eyebrow amber">EXAMPLE PAYLOAD</span>
                        <p>{m.payload}</p>
                      </div>
                      <label>
                        Planner source
                        <select
                          value={customPrompt ? "live" : mode}
                          disabled={customPrompt}
                          onChange={(e) => setMode(e.target.value)}
                        >
                          <option value="live">Live → Replay → Scripted</option>
                          <option value="scripted">
                            Scripted · deterministic demonstration
                          </option>
                          <option value="replay">Replay → Scripted</option>
                        </select>
                      </label>
                      <div className="row wrap">
                        <button
                          className="primary"
                          disabled={busy || !!active}
                          onClick={() => void run()}
                        >
                          Run mission <span>↗</span>
                        </button>
                        {mission === 2 && (
                          <button
                            disabled={busy || !!active}
                            onClick={() => void run(true)}
                          >
                            Run task 2
                          </button>
                        )}
                        <button
                          disabled={busy}
                          onClick={() => void snapshot("hardened")}
                        >
                          Apply hardened
                        </button>
                        <button
                          className="text-button"
                          onClick={() => void snapshot("vulnerable")}
                        >
                          Vulnerable
                        </button>
                      </div>
                      <p className="caption">
                        Unedited examples can run as labeled Scripted demos.
                        Custom text uses a Live model only; configure one in
                        Settings, then resume if it is unavailable. All tool
                        proposals still pass through this mission’s synthetic
                        controls.
                      </p>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            stream.current?.close();
                            await api(
                              "/missions/" + mission + "/reset",
                              "POST",
                            );
                            setSelected(undefined);
                            setEvents([]);
                            setSheet(emptySheet);
                            await refresh();
                          })
                        }
                      >
                        ↺ Reset this mission
                      </button>
                    </Panel>
                    <Panel>
                      <div className="row spread">
                        <p className="eyebrow">LEARNING LOOP</p>
                        <span className="mono amber">
                          {scores[mission - 1]?.automatic || 0} / 90
                        </span>
                      </div>
                      {[
                        "Observe the proposed action",
                        "Trace its failed boundary",
                        "Apply the containment control",
                        "Retest the legitimate workflow",
                      ].map((s, i) => (
                        <div className="check-step" key={s}>
                          <span>0{i + 1}</span>
                          {s}
                        </div>
                      ))}
                      <button
                        className="text-button"
                        onClick={() => setHint(Math.min(3, hint + 1))}
                      >
                        Reveal hint {Math.min(3, hint + 1)} of 3 ↓
                      </button>
                      {m.hints.slice(0, hint).map((h) => (
                        <p className="hint" key={h}>
                          {h}
                        </p>
                      ))}
                      <p className="caption">
                        Expected: malicious action denied; authorized task
                        succeeds. M6 compares inspection limits rather than
                        blocking the inspection.
                      </p>
                    </Panel>
                  </div>
                  <div className="section-head">
                    <h2>Execution trace</h2>
                    <div className="row">
                      <Chip
                        tone={selected?.source === "Live" ? "green" : "amber"}
                      >
                        {selected?.source || "WAITING"}
                      </Chip>
                      {selected && (
                        <span className="mono dim">
                          {selected.status} · {selected.provider}/
                          {selected.model}
                        </span>
                      )}
                    </div>
                  </div>
                  {selected?.status === "waiting_for_provider" && (
                    <div className="approval live-paused">
                      <div>
                        <strong>
                          Your experiment is paused because no live planner
                          returned a proposal.
                        </strong>
                        <p>
                          The prompt and tool history are saved. Configure a
                          planner in Settings, then resume this same
                          conversation.
                        </p>
                      </div>
                      <button onClick={() => setPage("Settings")}>
                        Configure planner
                      </button>
                      <button
                        className="primary"
                        onClick={() =>
                          void act(async () =>
                            watch(
                              await api<Task>(
                                "/tasks/" + selected.id + "/resume",
                                "POST",
                              ),
                            ),
                          )
                        }
                      >
                        Resume experiment <span>↗</span>
                      </button>
                    </div>
                  )}
                  {selected?.status === "pending_approval" && (
                    <div className="approval">
                      <strong>
                        Execution paused. This proposal needs your decision.
                      </strong>
                      <button
                        onClick={() =>
                          void act(async () =>
                            watch(
                              await api<Task>(
                                "/tasks/" + selected.id + "/approval",
                                "POST",
                                { allow: false },
                              ),
                            ),
                          )
                        }
                      >
                        Reject & continue
                      </button>
                      <button
                        onClick={() =>
                          void act(async () =>
                            watch(
                              await api<Task>(
                                "/tasks/" + selected.id + "/approval",
                                "POST",
                                { allow: true },
                              ),
                            ),
                          )
                        }
                      >
                        Approve once
                      </button>
                    </div>
                  )}
                  <Trace
                    events={events}
                    pins={sheet.pins}
                    onPin={(id) => void pin(id)}
                  />
                  <div className="section-head">
                    <h2>Your field notes</h2>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(async () => {
                          setSheet(
                            await api<Sheet>(
                              "/worksheets/" + mission,
                              "PUT",
                              sheet,
                            ),
                          );
                          setMessage("Worksheet saved locally.");
                          await refresh();
                        })
                      }
                    >
                      Save worksheet
                    </button>
                  </div>
                  <Panel>
                    <div className="worksheet">
                      {(
                        [
                          "observation",
                          "boundary",
                          "control",
                          "retest",
                          "impact",
                        ] as const
                      ).map((field) => (
                        <label key={field}>
                          {field.toUpperCase()}
                          <textarea
                            value={sheet[field]}
                            onChange={(e) =>
                              setSheet({ ...sheet, [field]: e.target.value })
                            }
                            placeholder={
                              {
                                observation: "What did the agent propose?",
                                boundary: "Which source acquired authority?",
                                control: "What blocked it?",
                                retest:
                                  "What proves the real task still works?",
                                impact:
                                  "Synthetic impact and possible real-world severity.",
                              }[field]
                            }
                          />
                        </label>
                      ))}
                      <label>
                        SELF-ASSESSMENT / 10
                        <input
                          type="number"
                          min="0"
                          max="10"
                          value={sheet.manual}
                          onChange={(e) =>
                            setSheet({
                              ...sheet,
                              manual: Math.max(
                                0,
                                Math.min(10, +e.target.value),
                              ),
                            })
                          }
                        />
                        <small>
                          Explain the boundary and impact. This is a manual
                          rubric field.
                        </small>
                      </label>
                    </div>
                  </Panel>
                </>
              )}
            </>
          )}
          {page === "Recon" && (
            <>
              <Panel>
                <p className="eyebrow">TRUST & AUTHORITY MAP</p>
                <h2>Know what the agent can reach.</h2>
                <p className="lead">
                  Untrusted ticket text, retrieved memory, tool results, and
                  tool descriptions enter the planner as data. Every proposed
                  action passes through the same execution gates.
                </p>
                <div className="boundary-map">
                  {[
                    "Context",
                    "Planner",
                    "Policy",
                    "IAM / MCP",
                    "Gateway / Runner",
                  ].map((s, i) => (
                    <React.Fragment key={s}>
                      <span>{s}</span>
                      {i < 4 && <b>→</b>}
                    </React.Fragment>
                  ))}
                </div>
                <button
                  onClick={() =>
                    void act(async () => setRecon(await api("/recon")))
                  }
                >
                  Refresh discovery
                </button>
              </Panel>
              <div className="section-head">
                <h2>Local discovery & synthetic state</h2>
                <Chip>READ ONLY</Chip>
              </div>
              <Panel>
                <pre>{JSON.stringify(recon, null, 2)}</pre>
              </Panel>
            </>
          )}
          {page === "Config" && (
            <div className="mission-grid">
              <Panel>
                <p className="eyebrow">ACTIVE SESSION POLICY</p>
                <h2>Make the boundary explicit.</h2>
                <label htmlFor="policy">YAML policy</label>
                <textarea
                  id="policy"
                  className="code-editor"
                  value={yaml}
                  onChange={(e) => setYaml(e.target.value)}
                  spellCheck={false}
                />
                <div className="row wrap">
                  <button
                    className="primary"
                    onClick={() =>
                      void act(async () => {
                        await api("/config", "PUT", { yaml });
                        await refresh();
                        setMessage(
                          "Valid policy applied atomically. Pending approvals remain paused.",
                        );
                      })
                    }
                  >
                    Apply policy <span>↗</span>
                  </button>
                  <button
                    onClick={() =>
                      void act(async () => {
                        const v = await api<{ valid: boolean; error?: string }>(
                          "/config/validate",
                          "POST",
                          { yaml },
                        );
                        setMessage(
                          v.valid
                            ? "Configuration valid."
                            : v.error || "Invalid configuration",
                        );
                      })
                    }
                  >
                    Validate
                  </button>
                </div>
              </Panel>
              <Panel>
                <p className="eyebrow">SNAPSHOTS</p>
                <h2>Compare the same proposal.</h2>
                <p className="lead">
                  Invalid configuration keeps the last valid rules. Policy
                  changes apply at the next tool gate; they never execute a
                  pending approval.
                </p>
                <div className="stack">
                  <button onClick={() => void snapshot("vulnerable")}>
                    Load vulnerable snapshot
                  </button>
                  <button onClick={() => void snapshot("hardened")}>
                    Load hardened snapshot
                  </button>
                </div>
                <p className="caption">
                  Scopes and provenance are assigned by the application. A
                  model's attribution never grants permission.
                </p>
                <p className="caption">
                  For file hot reload, atomically replace .data/active.yaml. A
                  session snapshot takes precedence until global reset.
                </p>
              </Panel>
            </div>
          )}
          {page === "Logs" && (
            <>
              {recordings.length > 0 && (
                <Panel>
                  <h2>Restart a genuine recording</h2>
                  <p>
                    Explicit restart applies the recorded policy and starts a
                    new task. Existing evidence is retained.
                  </p>
                  {recordings.map((r) => (
                    <button
                      key={r.id}
                      disabled={!!active}
                      onClick={() =>
                        void act(async () => {
                          const t = await api<Task>(
                            "/recordings/" + r.id + "/restart",
                            "POST",
                          );
                          setMission(t.mission);
                          setPage("Missions");
                          watch(t);
                        })
                      }
                    >
                      Replay M{r.mission} · {r.provider}/{r.model}
                    </button>
                  ))}
                </Panel>
              )}
              <div className="section-head">
                <h2>Task history</h2>
                <button
                  onClick={() =>
                    void act(async () =>
                      download("vulcan-evidence.json", await api("/export")),
                    )
                  }
                >
                  Export all evidence ↗
                </button>
              </div>
              <div className="log-list">
                {tasks.length === 0 && (
                  <Panel>
                    <p>No tasks yet. Run a mission to create a trace.</p>
                  </Panel>
                )}
                {tasks.map((t) => (
                  <button
                    key={t.id}
                    className={
                      selected?.id === t.id ? "history chosen" : "history"
                    }
                    onClick={() =>
                      void act(async () => {
                        setSelected(t);
                        setEvents(
                          await api<AuditEvent[]>("/tasks/" + t.id + "/events"),
                        );
                      })
                    }
                  >
                    <span className="mono">M{t.mission}</span>
                    <span>
                      {new Date(t.created * 1000).toLocaleTimeString()} ·{" "}
                      {t.id.slice(0, 8)}
                    </span>
                    <Chip>{t.source}</Chip>
                    <span>{t.status}</span>
                    <Chip tone={t.legitimate_success ? "green" : ""}>
                      {t.legitimate_success
                        ? "TASK SUCCEEDED"
                        : "NO VERIFIED OUTCOME"}
                    </Chip>
                  </button>
                ))}
              </div>
              {selected && (
                <>
                  <div className="section-head">
                    <h2>Immutable event evidence</h2>
                    <button
                      onClick={() =>
                        void act(async () =>
                          download(
                            "vulcan-" + selected.id + ".json",
                            await api("/tasks/" + selected.id + "/recording"),
                          ),
                        )
                      }
                    >
                      Export transcript
                    </button>
                  </div>
                  <Trace events={events} pins={[]} />
                </>
              )}
            </>
          )}
          {page === "Scoreboard" && (
            <>
              <Panel>
                <div className="score-hero">
                  <div>
                    <p className="eyebrow">EVIDENCE OVER ASSUMPTION</p>
                    <h2>
                      {total}
                      <span> / 700</span>
                    </h2>
                  </div>
                  <p>
                    30 points: observed baseline impact
                    <br />
                    40 points: hardened legitimate retest
                    <br />
                    20 points: two pinned events
                    <br />
                    10 points: manual self-assessment
                  </p>
                </div>
              </Panel>
              <div className="mission-list">
                {scores.map((s) => (
                  <div className="score-row" key={s.mission}>
                    <span className="mission-num">0{s.mission}</span>
                    <h3>{s.title}</h3>
                    <Chip tone={s.baseline ? "amber" : ""}>
                      BASELINE {s.baseline ? "✓" : "—"}
                    </Chip>
                    <Chip tone={s.hardened_retest ? "green" : ""}>
                      RETEST {s.hardened_retest ? "✓" : "—"}
                    </Chip>
                    <Chip>EVIDENCE {s.evidence ? "✓" : "—"}</Chip>
                    <strong>{s.automatic + s.manual} / 100</strong>
                  </div>
                ))}
              </div>
              <p className="caption">
                Scores are lab evidence, not live-provider calibration. Each
                task retains the controls active at its start; do not change
                controls mid-task when scoring a retest.
              </p>
            </>
          )}
          {page === "Settings" && settings && (
            <div className="mission-grid">
              <Panel>
                <p className="eyebrow">BRING YOUR OWN KEY</p>
                <h2>Choose your planner.</h2>
                <p className="lead">
                  openai → groq → openrouter → mistral → ollama → replay → scripted
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const submitted = key;
                    setKey("");
                    void act(async () => {
                      setSettings(
                        await api<Settings>("/settings", "POST", {
                          provider,
                          key: submitted,
                          ...(model ? { model } : {}),
                        }),
                      );
                      setMessage(
                        "Provider settings saved in server memory. Key input cleared.",
                      );
                    });
                  }}
                >
                  <label>
                    Provider
                    <select
                      value={provider}
                      onChange={(e) => {
                        setProvider(e.target.value);
                        setKey("");
                        setModel("");
                      }}
                    >
                      {settings.providers.map((p) => (
                        <option key={p.name} value={p.name}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    API key
                    <input
                      type="password"
                      autoComplete="off"
                      value={key}
                      onChange={(e) => setKey(e.target.value)}
                      placeholder="Paste a planner API key"
                      required
                      maxLength={500}
                    />
                  </label>
                  <label>
                    Model override (optional)
                    <input
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder={
                        settings.providers.find((p) => p.name === provider)
                          ?.model
                      }
                    />
                  </label>
                  <button className="primary" disabled={busy}>
                    Save to memory <span>↗</span>
                  </button>
                </form>
                <p className="caption">{settings.privacy}</p>
              </Panel>
              <Panel>
                <p className="eyebrow">AVAILABILITY</p>
                {settings.providers.map((p) => (
                  <div className="provider-row" key={p.name}>
                    <div>
                      <h3>
                        {p.name}{" "}
                        <Chip tone={p.configured ? "green" : ""}>
                          {p.configured ? "CONFIGURED" : "NO KEY"}
                        </Chip>
                      </h3>
                      <p className="mono dim">{p.model}</p>
                      <small>Cooldown: {p.cooldown_seconds}s</small>
                    </div>
                    <div>
                      <button
                        disabled={busy || !p.configured}
                        onClick={() =>
                          void act(async () => {
                            const result = await api<{ message: string }>(
                              "/settings/test",
                              "POST",
                              { provider: p.name },
                            );
                            setMessage(result.message);
                            await refresh();
                          })
                        }
                      >
                        Test
                      </button>
                      <button
                        className="text-button"
                        disabled={!p.configured}
                        onClick={() =>
                          void act(async () => {
                            setSettings(
                              await api<Settings>("/settings", "POST", {
                                provider: p.name,
                              }),
                            );
                            setMessage("Key removed.");
                          })
                        }
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                ))}
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={settings.offline}
                    onChange={(e) =>
                      void act(async () =>
                        setSettings(
                          await api<Settings>("/settings", "POST", {
                            offline: e.target.checked,
                          }),
                        ),
                      )
                    }
                  />
                  Offline mode · no planner network requests
                </label>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={settings.ollama}
                    onChange={(e) =>
                      void act(async () =>
                        setSettings(
                          await api<Settings>("/settings", "POST", {
                            ollama: e.target.checked,
                          }),
                        ),
                      )
                    }
                  />
                  Enable optional local Ollama
                </label>
                <p className="caption">
                  {settings.requests} / {rules?.request_budget} requests ·{" "}
                  {settings.tokens_reserved} / {rules?.token_budget} tokens
                  reserved
                </p>
                <p className="caption">{settings.quota_hint}</p>
                <button
                  className="danger"
                  onClick={() =>
                    void act(async () => {
                      stream.current?.close();
                      await api("/reset", "POST");
                      setSelected(undefined);
                      setEvents([]);
                      setSheet(emptySheet);
                      await refresh();
                      setMessage(
                        "Session reset. Synthetic state, evidence, budgets, and in-memory keys cleared.",
                      );
                    })
                  }
                >
                  Global reset · clear data & keys
                </button>
              </Panel>
            </div>
          )}
          {page === "Final Boss" && incident && (
            <>
              <Panel>
                <p className="eyebrow amber">180 EVENTS · ONE CAUSAL CHAIN</p>
                <h2>Contain an incident in progress.</h2>
                <p className="lead">{incident.label}</p>
                <p>
                  Find the poisoned source, reconstruct the boundary crossing,
                  then stop the next simulated action. Historical events remain
                  intact.
                </p>
                <div className="row wrap">
                  {Object.entries(incident.containment).map(([control, on]) => (
                    <button
                      disabled={on || busy}
                      key={control}
                      onClick={() =>
                        void act(async () =>
                          setIncident(
                            await api<Incident>(
                              "/containment/" + control,
                              "POST",
                            ),
                          ),
                        )
                      }
                    >
                      {on ? "✓ " : ""}
                      {control.replaceAll("_", " ")}
                    </button>
                  ))}
                  <button
                    className="primary"
                    onClick={() =>
                      void act(async () =>
                        setIncident(
                          await api<Incident>("/final-boss/advance", "POST"),
                        ),
                      )
                    }
                  >
                    Advance simulation <span>→</span>
                  </button>
                </div>
                {incident.actions.map((a) => (
                  <p className="incident-action" key={a.id}>
                    <Chip tone={a.verdict === "DENY" ? "green" : "amber"}>
                      {a.verdict}
                    </Chip>{" "}
                    {a.tool} <small>{a.source}</small>
                  </p>
                ))}
              </Panel>
              <div className="section-head">
                <h2>Historical timeline</h2>
                <Chip>RETAINED EVIDENCE</Chip>
              </div>
              <div className="timeline">
                {incident.events.map((e) => (
                  <div
                    className={
                      "timeline-row " +
                      (e.kind === "health" ? "noise" : "signal")
                    }
                    key={e.id}
                  >
                    <span className="mono">
                      {String(e.sequence).padStart(3, "0")}
                    </span>
                    <Chip>{e.source}</Chip>
                    <strong>{e.kind}</strong>
                    <span>{JSON.stringify(e.data)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          {page === "Facilitator" && (
            <div className="mission-grid">
              <Panel>
                <p className="eyebrow">OPTIONAL WORKSHOP FLOW</p>
                <h2>
                  Go solo.
                  <br />
                  Keep the structure.
                </h2>
                <div className="timer mono">
                  {String(Math.floor(remaining / 60)).padStart(2, "0")}:
                  {String(remaining % 60).padStart(2, "0")}
                </div>
                <div className="row">
                  <button onClick={() => setTimer(!timer)}>
                    {timer ? "Pause" : "Start"} timer
                  </button>
                  <button
                    onClick={() => {
                      setTimer(false);
                      setRemaining(115 * 60);
                    }}
                  >
                    Reset timer
                  </button>
                </div>
                {[
                  ["00–10", "Safety, setup & recon"],
                  ["10–30", "Goal hijack & memory poison"],
                  ["30–55", "Tool output & scoped privilege"],
                  ["55–80", "Exfiltration & execution containment"],
                  ["80–95", "Rogue MCP update"],
                  ["95–110", "Final Boss investigation"],
                  ["110–115", "Evidence review & closing"],
                ].map(([time, text]) => (
                  <div className="agenda" key={time}>
                    <span className="mono amber">{time}</span>
                    <span>{text}</span>
                  </div>
                ))}
              </Panel>
              <Panel>
                <p className="eyebrow">LOCAL MISSION LINK</p>
                {qr && (
                  <img
                    className="qr"
                    src={qr}
                    alt="QR code for this local machine's mission link"
                  />
                )}
                <p className="caption">
                  Generated locally. A localhost QR link opens the lab only on
                  this machine; no classroom hosting is configured.
                </p>
                {[
                  "Use only synthetic data and lab destinations.",
                  "Run vulnerable before hardened; preserve the trace.",
                  "Pin the proposed attack and its control decision.",
                  "Verify a legitimate outcome before awarding retest points.",
                  "Label scripted demonstrations and simulated runner results.",
                ].map((text) => (
                  <label className="toggle" key={text}>
                    <input type="checkbox" />
                    {text}
                  </label>
                ))}
                <blockquote>
                  Observe the attack. Trace the boundary. Apply the control.
                  Prove the legitimate workflow still works.
                </blockquote>
                <p className="caption">
                  Working closing copy. The original PRD was unavailable in the
                  accepted handoff.
                </p>
              </Panel>
            </div>
          )}
          <footer>
            <span className="mono">VULCAN / 1.2</span>
            <span>Observe. Contain. Prove.</span>
            <span className="mono">SYNTHETIC BY DESIGN</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
function Trace({
  events,
  pins,
  onPin,
}: {
  events: AuditEvent[];
  pins: string[];
  onPin?: (id: string) => void;
}) {
  if (!events.length)
    return (
      <div className="empty">
        <Glyph />
        <h3>The trace starts here.</h3>
        <p>
          Run a mission to inspect context, proposals, decisions, and results.
        </p>
      </div>
    );
  const actions = new Map<string, AuditEvent[]>();
  const standalone: AuditEvent[] = [];
  events.forEach((e) => {
    if (e.action_id) {
      actions.set(e.action_id, [...(actions.get(e.action_id) || []), e]);
    } else standalone.push(e);
  });
  return (
    <div className="trace" aria-label="Task execution trace">
      {standalone
        .filter((e) => e.kind === "context")
        .map((e) => (
          <Panel key={e.id}>
            <div className="row spread">
              <p className="eyebrow">CONTEXT SEGMENTS</p>
              <Chip>{e.source}</Chip>
            </div>
            {((e.data as { segments?: ContextSegment[] }).segments || []).map(
              (s) => (
                <div className={"context " + s.trust} key={s.id}>
                  <Chip>{s.trust.toUpperCase()}</Chip>
                  <small className="mono">{s.provenance}</small>
                  <p>{s.text}</p>
                </div>
              ),
            )}
            <small>
              Likely cause highlights are explanatory evidence only.
            </small>
          </Panel>
        ))}
      {[...actions].map(([id, group]) => {
        const p = group.find((e) => e.kind === "proposal")?.data as
          | Proposal
          | undefined;
        const decisions = group.filter((e) => e.kind === "decision");
        const result = group.find((e) => e.kind === "result")?.data as
          | ToolResult
          | undefined;
        return (
          <Panel key={id}>
            <div className="row spread">
              <p className="eyebrow">ACTION {id.slice(0, 8)}</p>
              <div className="row">
                <Chip tone={group[0].source === "Live" ? "green" : "amber"}>
                  {group[0].source}
                </Chip>
                <small className="mono dim">
                  {group[0].provider} / {group[0].model}
                </small>
                {onPin && group.find((e) => e.kind === "proposal") && (
                  <button
                    className="pin"
                    onClick={() =>
                      onPin(group.find((e) => e.kind === "proposal")!.id)
                    }
                  >
                    {pins.includes(group.find((e) => e.kind === "proposal")!.id)
                      ? "◆ Pinned proposal"
                      : "◇ Pin proposal"}
                  </button>
                )}
              </div>
            </div>
            <div className="action-grid">
              <div>
                <h3>{p?.tool || "Invalid proposal"}</h3>
                <pre>
                  {JSON.stringify(p?.arguments || group[0].data, null, 2)}
                </pre>
                <details>
                  <summary>Model-generated Thought · unverified</summary>
                  <p>{p?.thought}</p>
                </details>
              </div>
              <div>
                {decisions.map((d) => {
                  const data = d.data as Decision;
                  return (
                    <div className="decision" key={d.id}>
                      <Chip
                        tone={
                          data.verdict === "ALLOW"
                            ? "amber"
                            : data.verdict === "DENY"
                              ? "green"
                              : "amber"
                        }
                      >
                        {data.verdict}
                      </Chip>
                      <p>{data.reason}</p>
                      <small className="mono">{data.control}</small>
                      {onPin && (
                        <button className="pin" onClick={() => onPin(d.id)}>
                          {pins.includes(d.id)
                            ? "◆ Pinned decision"
                            : "◇ Pin decision"}
                        </button>
                      )}
                    </div>
                  );
                })}
                {result && (
                  <details open>
                    <summary>Tool result · {result.status}</summary>
                    <pre>{JSON.stringify(result.data, null, 2)}</pre>
                    <small>
                      {result.provenance} · {result.tags?.join(", ")}
                    </small>
                  </details>
                )}
              </div>
            </div>
          </Panel>
        );
      })}
      {standalone
        .filter((e) => e.kind !== "context")
        .map((e) => (
          <div
            className={
              "trace-system " + (e.kind === "complete" ? "complete" : "")
            }
            key={e.id}
          >
            <Chip>{e.source}</Chip>
            <span className="mono">{e.kind}</span>
            <span>{JSON.stringify(e.data)}</span>
          </div>
        ))}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
