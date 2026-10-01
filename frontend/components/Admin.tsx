"use client";
import DemoWorkspace from "./DemoWorkspace";
import { useEffect, useRef, useState } from "react";
import Brand from "./Brand";
import Login from "./Login";
import { api, mutate, money } from "@/lib/api";
type Run = {
  id: string;
  scenario: string;
  revision: number;
  protection: boolean;
  binding: string;
};
type Event = {
  run_id: string;
  scenario: string;
  candidate_output: string;
  raw_model_output: string;
  final_output: string;
  candidate_hash: string;
  trace_id: string | null;
  decision: Record<string, unknown>;
  action_decisions: Record<string, unknown>[];
  endpoint: string;
  model: string;
  duration_seconds: number;
  evaluation: Record<string, unknown>;
};
type Status = {
  provider: string;
  model: string;
  provider_status: { state: string };
  galileo: {
    state: string;
    enabled: boolean;
    revision: number;
    connection: string;
    last_checked_at: number | null;
    last_connected_at: number | null;
    export: string;
    last_error: string | null;
  };
  project: string;
  log_stream: string;
  console_url: string | null;
  protection_status: string;
  demo_mode: "presenter" | "workshop";
  connection: {
    galileo_project: string;
    galileo_log_stream: string;
    galileo_console_url: string;
    galileo_api_url: string;
    agent_control_url: string;
    galileo_api_key_set: boolean;
    galileo_api_key_masked: string;
    splunk_ao_console_url: string;
    splunk_ao_api_url: string;
    splunk_ao_realm: string;
    splunk_ao_api_key_set: boolean;
    splunk_ao_api_key_masked: string;
    splunk_ao_o11y_token_set: boolean;
    splunk_ao_o11y_token_masked: string;
    splunk_ao_o11y_api_token_set: boolean;
    splunk_ao_o11y_api_token_masked: string;
  };
  observability: {
    active: "galileo" | "splunk_ao";
    backends: {
      id: "galileo" | "splunk_ao";
      name: string;
      stream_label: string;
      active: boolean;
      configured: boolean;
      mode: "" | "o11y" | "standalone";
    }[];
  };
  endpoints: {
    endpoints: {
      id: string;
      name: string;
      provider: "openai" | "anthropic" | "ollama";
      model: string;
      base_url: string;
      api_key_set: boolean;
      api_key_masked: string;
      active: boolean;
    }[];
    active_endpoint: string;
  };
  run: Run | null;
  events: Event[];
  scenarios: Record<string, { prompt: string; evaluation: string | null }>;
  dataset: {
    seed: number;
    reference_date: string;
    dataset_version: number;
    transaction_count: number;
  };
};
export default function Admin() {
  const [logged, setLogged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<Status>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [expected, setExpected] = useState<Record<string, unknown>>();
  // Sharon AI and "custom" are OpenAI-compatible endpoints: same provider, different base URL.
  const endpoints = {
    openai: { label: "OpenAI", provider: "openai", url: "", needsUrl: false, needsKey: true },
    anthropic: { label: "Anthropic", provider: "anthropic", url: "", needsUrl: false, needsKey: true },
    ollama: {
      label: "Ollama (local)",
      provider: "ollama",
      url: "http://host.docker.internal:11434",
      needsUrl: true,
      needsKey: false,
    },
    sharonai: {
      label: "Sharon AI",
      provider: "openai",
      url: "https://inference.sharonai.cloud/api/v1",
      needsUrl: true,
      needsKey: true,
    },
    custom: { label: "Custom (OpenAI-compatible)", provider: "openai", url: "", needsUrl: true, needsKey: true },
  } as const;
  type EndpointKey = keyof typeof endpoints;
  const [endpoint, setEndpoint] = useState<EndpointKey>("openai");
  const [model, setModel] = useState({ id: "", name: "", api_key: "", model: "", base_url: "" });
  const [tab, setTab] = useState<"demo" | "evidence" | "setup" | "tools">("demo");
  const landed = useRef(false);
  const [conn, setConn] = useState({
    galileo_api_key: "",
    splunk_ao_api_key: "",
    splunk_ao_o11y_token: "",
    splunk_ao_o11y_api_token: "",
    galileo_project: "",
    galileo_log_stream: "",
    galileo_console_url: "",
    galileo_api_url: "",
    agent_control_url: "",
    splunk_ao_console_url: "",
    splunk_ao_api_url: "",
    splunk_ao_realm: "",
  });
  const [seed, setSeed] = useState("42");
  const [date, setDate] = useState("2026-09-15");
  async function refresh() {
    try {
      const s = await api<Status>("demo-admin/status");
      if (!landed.current) {
        landed.current = true;
        if (s.demo_mode === "workshop" && !s.connection.galileo_api_key_set) setTab("setup");
        // Seed the form from what is saved so a participant edits it rather than retyping.
        // The key is never seeded: it only ever arrives masked.
        setConn((c) => ({
          ...c,
          galileo_project: s.connection.galileo_project,
          galileo_log_stream: s.connection.galileo_log_stream,
          galileo_console_url: s.connection.galileo_console_url,
          galileo_api_url: s.connection.galileo_api_url,
          agent_control_url: s.connection.agent_control_url,
          splunk_ao_console_url: s.connection.splunk_ao_console_url,
          splunk_ao_api_url: s.connection.splunk_ao_api_url,
          splunk_ao_realm: s.connection.splunk_ao_realm,
        }));
      }
      setStatus(s);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    api<{ authenticated: boolean }>("demo-admin/session")
      .then((s) => {
        setLogged(s.authenticated);
        if (s.authenticated) refresh();
      })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (!logged) return;
    const interval = setInterval(refresh, 7000);
    return () => clearInterval(interval);
  }, [logged]);
  useEffect(() => {
    if (status) {
      setSeed(String(status.dataset.seed));
      setDate(status.dataset.reference_date);
    }
  }, [status?.dataset.dataset_version]);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  // The connection form follows the active backend: Splunk AO's two deployment modes need
  // different credentials, and showing all of them at once invites filling in the wrong set.
  const activeId = status?.observability.active ?? "galileo";
  const activeBackend = status?.observability.backends.find((b) => b.active) ?? {
    id: "galileo" as const, name: "Galileo", stream_label: "log stream", active: true,
    configured: false, mode: "" as const,
  };
  const streamLabel = activeBackend.stream_label.replace(/^./, (c) => c.toUpperCase());
  // Splunk AO's two deployments are mutually exclusive and need different credentials. Show one
  // set, chosen here, rather than nine fields where six are wrong for whichever you are using.
  const [aoMode, setAoMode] = useState<"o11y" | "standalone">("o11y");
  const connectionFields: [keyof typeof conn, string, string][] =
    activeId === "splunk_ao"
      ? aoMode === "o11y"
        ? [
            ["splunk_ao_realm", "Realm, e.g. us1", "text"],
            ["splunk_ao_o11y_token", "Access token (INGEST + agent_observability_admin)", "password"],
            ["splunk_ao_o11y_api_token", "API token — optional, only to separate CRUD from ingest", "password"],
            ["galileo_project", "Project", "text"],
            ["galileo_log_stream", streamLabel, "text"],
            ["agent_control_url", "Agent Control URL — blank derives it from the realm", "text"],
          ]
        : [
            ["splunk_ao_api_key", "API key", "password"],
            ["splunk_ao_console_url", "Console URL", "text"],
            ["splunk_ao_api_url", "API URL — optional, derived from the console URL", "text"],
            ["galileo_project", "Project", "text"],
            ["galileo_log_stream", streamLabel, "text"],
            ["agent_control_url", "Agent Control URL", "text"],
          ]
      : [
          ["galileo_api_key", "API key", "password"],
          ["galileo_project", "Project", "text"],
          ["galileo_log_stream", streamLabel, "text"],
          ["galileo_console_url", "Console URL", "text"],
          ["galileo_api_url", "API URL", "text"],
          ["agent_control_url", "Agent Control URL", "text"],
        ];
  function secretPlaceholder(key: string) {
    const connection = status?.connection as Record<string, string | boolean> | undefined;
    const set = connection?.[`${key}_set`];
    if (set === undefined) return "";
    return set ? `${String(connection?.[`${key}_masked`])} — leave blank to keep` : "paste your key";
  }
  const keySummary =
    activeId === "splunk_ao"
      ? status?.connection.splunk_ao_o11y_token_set
        ? `O11y token ${status.connection.splunk_ao_o11y_token_masked}`
        : status?.connection.splunk_ao_api_key_set
          ? `API key ${status.connection.splunk_ao_api_key_masked}`
          : "No credentials set"
      : status?.connection.galileo_api_key_set
        ? `API key ${status.connection.galileo_api_key_masked}`
        : "No API key set";

  return (
    <>
      <header className="public-header">
        <Brand />
        <span className="badge pending">Presenter workspace</span>
        {logged && (
          <button
            className="text-button"
            onClick={() =>
              action(async () => {
                await mutate("demo-admin/logout", {}, true);
                setLogged(false);
                setStatus(undefined);
              })
            }
          >
            Presenter log out
          </button>
        )}
      </header>
      <main id="main" className="admin-main">
        {loading ? (
          <p role="status">Checking presenter session…</p>
        ) : !logged ? (
          <section className="login-box admin-login">
            <Login
              admin
              onSuccess={() => {
                setLogged(true);
                refresh();
              }}
            />
          </section>
        ) : (
          <>
            <div className="page-heading">
              <div className="eyebrow">
                OBSERVE → EVALUATE → DETECT → PROTECT
              </div>
              <h1>
                Demo workspace<span className="green">.</span>
              </h1>
              <p className="muted">
                Actual configuration, controlled faults, and live evidence.
                Live controls for your connected banking chat.
              </p>
            </div>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {notice && (
              <p className="notice" role="status">
                {notice}
              </p>
            )}
            {status && (
              <>
                <div className="admin-status-grid">
                  <article className="admin-card">
                    <span className="mini-label">MODEL PROVIDER</span>
                    <h3>{status.provider}</h3>
                    <p>{status.model}</p>
                    <span className="badge">
                      {status.provider_status.state}
                    </span>
                    <small>
                      Provider/model changes require .env edit and restart.
                    </small>
                  </article>
                  <article className="admin-card">
                    <span className="mini-label">GALILEO</span>
                    <h3 aria-live="polite">
                      {status.galileo.enabled
                        ? status.galileo.connection
                        : "disabled"}
                    </h3>
                    <button
                      className="button outline small"
                      disabled={
                        busy || status.galileo.connection === "checking"
                      }
                      onClick={() =>
                        action(() =>
                          mutate(
                            "demo-admin/galileo",
                            {
                              enabled: !status.galileo.enabled,
                              expected_revision: status.galileo.revision,
                            },
                            true,
                            "PUT",
                          ),
                        )
                      }
                    >
                      {status.galileo.enabled
                        ? "Disable Galileo"
                        : "Enable Galileo"}
                    </button>
                    <button
                      className="text-button"
                      disabled={busy || !status.galileo.enabled}
                      onClick={() =>
                        action(() =>
                          mutate("demo-admin/galileo/check", {}, true),
                        )
                      }
                    >
                      Check Galileo connection
                    </button>
                    <small>
                      Enabled by default. This switch applies to all demo chats
                      and is saved across restarts.
                    </small>
                    {status.galileo.last_checked_at && (
                      <small>
                        Last checked:{" "}
                        {new Date(
                          status.galileo.last_checked_at * 1000,
                        ).toLocaleString()}
                      </small>
                    )}
                    {status.galileo.last_connected_at && (
                      <small>
                        Last connected:{" "}
                        {new Date(
                          status.galileo.last_connected_at * 1000,
                        ).toLocaleString()}
                      </small>
                    )}
                    <p>
                      {status.project} / {status.log_stream}
                    </p>
                    <span className="badge">
                      Export: {status.galileo.export}
                    </span>
                    {status.galileo.last_error && (
                      <small>{status.galileo.last_error}</small>
                    )}
                    {status.console_url && (
                      <a
                        href={status.console_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-link"
                      >
                        Open configured console ↗
                      </a>
                    )}
                  </article>
                  <article className="admin-card">
                    <span className="mini-label">DATASET</span>
                    <h3>Version {status.dataset.dataset_version}</h3>
                    <p>
                      Seed {status.dataset.seed} ·{" "}
                      {status.dataset.reference_date}
                    </p>
                    <span className="badge">
                      {status.dataset.transaction_count} transactions
                    </span>
                    <button
                      className="button outline small"
                      disabled={busy}
                      title="Restore balances and transactions after a Money Transfer run"
                      onClick={() => {
                        if (confirm("Restore the dataset? Balances and transactions return to their seeded values and conversations are cleared."))
                          action(() =>
                            mutate(
                              "demo-admin/dataset/reset",
                              {
                                confirmed: true,
                                expected_version: status.dataset.dataset_version,
                                seed: status.dataset.seed,
                                reference_date: status.dataset.reference_date,
                              },
                              true,
                            ),
                          );
                      }}
                    >
                      Reset balance
                    </button>
                  </article>
                </div>
                <nav className="admin-tabs" role="tablist" aria-label="Presenter sections">
                  {(
                    [
                      ["demo", "Demo"],
                      ["evidence", "Evidence"],
                      ["setup", "Setup"],
                      ["tools", "Troubleshooting"],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      role="tab"
                      className="admin-tab"
                      aria-selected={tab === key}
                      onClick={() => setTab(key)}
                    >
                      {label}
                      {key === "setup" && !status.connection.galileo_api_key_set && (
                        <span className="tab-dot" title="No Galileo API key set yet">
                          ●
                        </span>
                      )}
                    </button>
                  ))}
                </nav>
                <div role="tabpanel" hidden={tab !== "demo"}>
                  {status.endpoints.endpoints.length > 1 && (
                    <div className="switcher">
                      <span className="mini-label">MODEL</span>
                      {status.endpoints.endpoints.map((e) => (
                        <button
                          key={e.id}
                          className={`button ${e.active ? "" : "outline"} small`}
                          aria-pressed={e.active}
                          disabled={busy || e.active}
                          title={`${e.model}${e.base_url ? ` · ${e.base_url}` : ""}`}
                          onClick={() =>
                            action(async () => {
                              await mutate("demo-admin/endpoints/active", { id: e.id }, true);
                              setNotice(`Switched to ${e.name}. Applies to your next message.`);
                            })
                          }
                        >
                          {e.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <DemoWorkspace onEvidence={refresh} />
                </div>
                <div role="tabpanel" hidden={tab !== "evidence"}>
                  <section className="admin-card">
                    <h2>Latest chat evidence</h2>
                    <button
                      className="button outline small"
                      disabled={busy}
                      onClick={() =>
                        action(() =>
                          mutate("demo-admin/evaluations/refresh", {}, true),
                        )
                      }
                    >
                      Fetch actual Galileo scores
                    </button>
                    {!status.events.length ? (
                      <p className="muted">
                        No demo responses yet. No scores or decisions are
                        fabricated.
                      </p>
                    ) : (
                      status.events
                        .slice()
                        .reverse()
                        .map((e) => (
                          <details className="event" key={e.run_id}>
                            <summary>
                              {e.scenario} · {e.endpoint || e.model} · {e.duration_seconds}s ·{" "}
                              {e.action_decisions?.length
                                ? `action ${String(e.action_decisions[0].decision)}`
                                : "live model + optional injection"}
                            </summary>
                            <p className="mono">
                              Run {e.run_id}
                              <br />
                              Trace {e.trace_id || "unavailable"}
                              <br />
                              Candidate hash {e.candidate_hash}
                            </p>
                            <h3>Raw model output</h3>
                            <p>{e.raw_model_output}</p>
                            <h3>Candidate output</h3>
                            <p>{e.candidate_output}</p>
                            <h3>Customer-visible answer</h3>
                            <p>{e.final_output}</p>
                            <pre>
                              {JSON.stringify(
                                {
                                  decision: e.decision,
                                  evaluation: e.evaluation,
                                  action_decisions: e.action_decisions,
                                },
                                null,
                                2,
                              )}
                            </pre>
                          </details>
                        ))
                    )}
                  </section>
                </div>
                <div role="tabpanel" hidden={tab !== "setup"}>
                  <section className="admin-card">
                    <h2>Model endpoint</h2>
                  <p className="muted">
                    Which model the agent calls. Sharon AI and other OpenAI-compatible services
                    use the OpenAI protocol with their own base URL.
                  </p>
                  <ul className="endpoint-list">
                    {status.endpoints.endpoints.length === 0 && (
                      <li className="muted">No endpoints saved yet.</li>
                    )}
                    {status.endpoints.endpoints.map((e) => (
                      <li key={e.id} className={e.active ? "endpoint active" : "endpoint"}>
                        <label>
                          <input
                            type="radio"
                            name="active-endpoint"
                            checked={e.active}
                            disabled={busy}
                            onChange={() =>
                              action(async () => {
                                await mutate("demo-admin/endpoints/active", { id: e.id }, true);
                                setNotice(`Switched to ${e.name}. Applies to your next message.`);
                              })
                            }
                          />
                          <strong>{e.name}</strong>
                        </label>
                        <span className="muted">
                          {e.model}
                          {e.base_url && ` · ${e.base_url}`}
                          {e.api_key_set && ` · key ${e.api_key_masked}`}
                        </span>
                        <span className="endpoint-actions">
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() => {
                              setModel({
                                id: e.id,
                                name: e.name,
                                api_key: "",
                                model: e.model,
                                base_url: e.base_url,
                              });
                              setEndpoint(
                                e.provider === "anthropic"
                                  ? "anthropic"
                                  : e.provider === "ollama"
                                    ? "ollama"
                                    : e.base_url.startsWith("https://inference.sharonai.cloud")
                                      ? "sharonai"
                                      : e.base_url
                                        ? "custom"
                                        : "openai",
                              );
                            }}
                          >
                            Edit
                          </button>
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() => {
                              if (confirm(`Remove ${e.name}?`))
                                action(() =>
                                  mutate(`demo-admin/endpoints/${e.id}`, {}, true, "DELETE"),
                                );
                            }}
                          >
                            Remove
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                  <h3>{model.id ? "Edit endpoint" : "Add an endpoint"}</h3>
                  <div className="admin-stack">
                    <div>
                      <label htmlFor="ep_name">Name</label>
                      <input
                        id="ep_name"
                        type="text"
                        autoComplete="off"
                        placeholder="Ollama · gemma4"
                        value={model.name}
                        onChange={(e) => setModel({ ...model, name: e.target.value })}
                      />
                    </div>
                    <div>
                      <label htmlFor="endpoint">Provider</label>
                      <select
                        id="endpoint"
                        value={endpoint}
                        onChange={(e) => {
                          const next = e.target.value as EndpointKey;
                          setEndpoint(next);
                          setModel({ ...model, base_url: endpoints[next].url });
                        }}
                      >
                        {(Object.keys(endpoints) as EndpointKey[]).map((key) => (
                          <option key={key} value={key}>
                            {endpoints[key].label}
                          </option>
                        ))}
                      </select>
                    </div>
                    {endpoints[endpoint].needsUrl && (
                      <div>
                        <label htmlFor="base_url">Base URL</label>
                        <input
                          id="base_url"
                          type="text"
                          autoComplete="off"
                          placeholder="https://api.example.com/v1"
                          value={model.base_url}
                          onChange={(e) => setModel({ ...model, base_url: e.target.value })}
                        />
                      </div>
                    )}
                    {endpoints[endpoint].needsKey && (
                      <div>
                        <label htmlFor="model_key">API key</label>
                        <input
                          id="model_key"
                          type="password"
                          autoComplete="off"
                          placeholder={model.id ? "leave blank to keep" : "paste your key"}
                          value={model.api_key}
                          onChange={(e) => setModel({ ...model, api_key: e.target.value })}
                        />
                      </div>
                    )}
                    <div>
                      <label htmlFor="model_name">Model</label>
                      <input
                        id="model_name"
                        type="text"
                        autoComplete="off"
                        placeholder="gpt-4o-mini-2024-07-18"
                        value={model.model}
                        onChange={(e) => setModel({ ...model, model: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="admin-actions">
                    <button
                      className="button small"
                      disabled={busy}
                      onClick={() =>
                        action(async () => {
                          await mutate(
                            "demo-admin/endpoints",
                            {
                              id: model.id,
                              name: model.name,
                              provider: endpoints[endpoint].provider,
                              api_key: model.api_key,
                              model: model.model,
                              base_url: model.base_url,
                            },
                            true,
                            "PUT",
                          );
                          setModel({ id: "", name: "", api_key: "", model: "", base_url: "" });
                          setNotice("Endpoint saved. Use Test my setup to call it.");
                        })
                      }
                    >
                      {model.id ? "Save changes" : "Add endpoint"}
                    </button>
                    {model.id && (
                      <button
                        className="button outline small"
                        disabled={busy}
                        onClick={() =>
                          setModel({ id: "", name: "", api_key: "", model: "", base_url: "" })
                        }
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </section>
                <section className="admin-card">
                  <h2>Connect to Splunk Agent Observability / Galileo</h2>
                  {status.demo_mode === "workshop" && (
                    <p className="muted">
                      Create the project, log stream, evaluators and guardrail in the Galileo
                      console yourself — that is the lab. This panel only points the app at them.
                    </p>
                  )}
                    <p className="muted">
                      Paste your own API key and project. Saved to this instance only and applied
                      immediately — no restart. The key is never shown again once saved.
                    </p>
                    {/* One backend at a time. Two would leave Agent Control without an
                        adjudicator, and two tenants disagreeing on one tool call has no answer. */}
                    <div className="admin-actions" role="group" aria-label="Observability backend">
                      {status.observability.backends.map((b) => (
                        <button
                          key={b.id}
                          className={`button small${b.active ? "" : " outline"}`}
                          aria-pressed={b.active}
                          disabled={busy || b.active}
                          title={`Send traces to ${b.name}`}
                          onClick={() =>
                            action(async () => {
                              await mutate("demo-admin/backends/active", { id: b.id }, true);
                              setNotice(`Now logging to ${b.name}. The conversation was reset.`);
                            })
                          }
                        >
                          {b.name}
                          {b.configured ? "" : " (not configured)"}
                        </button>
                      ))}
                    </div>
                    {activeId === "splunk_ao" && (
                      <div className="admin-actions" role="group" aria-label="Splunk AO deployment">
                        {(
                          [
                            ["o11y", "Observability Cloud"],
                            ["standalone", "Standalone"],
                          ] as const
                        ).map(([id, label]) => (
                          <button
                            key={id}
                            className={`button small${aoMode === id ? "" : " outline"}`}
                            aria-pressed={aoMode === id}
                            disabled={busy}
                            onClick={() => setAoMode(id)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                    <p>
                      <strong>{activeBackend.name}</strong>
                      {" · "}
                      {keySummary}
                      {" · "}
                      {status.galileo.connection}
                    </p>
                    <div className="admin-stack">
                      {connectionFields.map(([key, label, type]) => (
                        <div key={key}>
                          <label htmlFor={key}>{label}</label>
                          <input
                            id={key}
                            type={type}
                            autoComplete="off"
                            placeholder={secretPlaceholder(key)}
                            value={conn[key]}
                            onChange={(e) => setConn({ ...conn, [key]: e.target.value })}
                          />
                        </div>
                      ))}
                    </div>
                    <div className="admin-actions">
                      <button
                        className="button small"
                        disabled={busy}
                        onClick={() =>
                          action(async () => {
                            await mutate("demo-admin/galileo/connection", conn, true, "PUT");
                            setConn({
                              ...conn,
                              galileo_api_key: "",
                              splunk_ao_api_key: "",
                              splunk_ao_o11y_token: "",
                              splunk_ao_o11y_api_token: "",
                            });
                            setNotice("Galileo connection saved.");
                          })
                        }
                      >
                        Save and connect
                      </button>
                      {/* Workshop participants create metrics and controls themselves; that is
                          the lab. This shortcut would skip it. */}
                      {status.demo_mode !== "workshop" && (
                      <button
                        className="button outline small"
                        disabled={busy || !status.connection.galileo_api_key_set}
                        title="Enable the metrics on your log stream and bind the transfer control"
                        onClick={() =>
                          action(async () => {
                            const job = await mutate<{ job_id: string }>(
                              "demo-admin/galileo/setup",
                              {},
                              true,
                            );
                            setNotice("Setting up your project...");
                            let done = false;
                            while (!done) {
                              await new Promise((r) => setTimeout(r, 2000));
                              const result = await api<{ state: string; result: unknown }>(
                                `demo-admin/preflight/${job.job_id}`,
                              );
                              done = result.state !== "running";
                              if (done)
                                setNotice(
                                  `Project setup ${result.state}: ${JSON.stringify(result.result)}`,
                                );
                            }
                          })
                        }
                      >
                        Set up my project
                      </button>
                    )}
                    </div>
                  </section>
                </div>
                <div role="tabpanel" hidden={tab !== "tools"}>
                  <section className="admin-card">
                    <h2>{status.demo_mode === "workshop" ? "Check my setup" : "Demo diagnostics"}</h2>
                    <div className="admin-actions">
                      <button
                        className="button outline small"
                        disabled={busy}
                        onClick={() =>
                          action(async () => {
                            const job = await mutate<{ job_id: string }>(
                              "demo-admin/preflight",
                              {},
                              true,
                            );
                            setNotice(
                              "Preflight started. This explicitly makes model API calls.",
                            );
                            let done = false;
                            while (!done) {
                              await new Promise((r) => setTimeout(r, 1500));
                              const result = await api<{
                                state: string;
                                result: unknown;
                              }>(`demo-admin/preflight/${job.job_id}`);
                              done = result.state !== "running";
                              if (done)
                                setNotice(
                                  `Preflight ${result.state}: ${JSON.stringify(result.result)}`,
                                );
                            }
                          })
                        }
                      >
                        Test my setup
                      </button>
                      <button
                        className="button outline small"
                        onClick={() =>
                          action(async () =>
                            setExpected(await api("demo-admin/expected-results")),
                          )
                        }
                      >
                        Inspect expected results
                      </button>
                    </div>
                    {expected && <pre>{JSON.stringify(expected, null, 2)}</pre>}
                  </section>
                  {status.demo_mode !== "workshop" && (
                  <section className="admin-card">
                    <h2>Reset synthetic data</h2>
                    <p className="muted">
                      Reseeding replaces the dataset and invalidates conversations
                      and before/after comparisons.
                    </p>
                    <div className="admin-controls">
                      <div>
                        <label htmlFor="seed">Seed</label>
                        <input
                          id="seed"
                          type="number"
                          value={seed}
                          onChange={(e) => setSeed(e.target.value)}
                        />
                      </div>
                      <div>
                        <label htmlFor="reference">Reference date</label>
                        <input
                          id="reference"
                          type="date"
                          value={date}
                          onChange={(e) => setDate(e.target.value)}
                        />
                      </div>
                      <button
                        className="button outline small"
                        disabled={busy}
                        onClick={() => {
                          if (
                            confirm(
                              "Replace the synthetic dataset and clear all conversations and comparisons?",
                            )
                          )
                            action(() =>
                              mutate(
                                "demo-admin/dataset/reset",
                                {
                                  confirmed: true,
                                  expected_version:
                                    status.dataset.dataset_version,
                                  seed: Number(seed),
                                  reference_date: date,
                                },
                                true,
                              ),
                            );
                        }}
                      >
                        Confirm and reset data
                      </button>
                    </div>
                  </section>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}
