"use client";
import DemoWorkspace from "./DemoWorkspace";
import { useEffect, useState } from "react";
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
  const [seed, setSeed] = useState("42");
  const [date, setDate] = useState("2026-09-15");
  async function refresh() {
    try {
      const s = await api<Status>("demo-admin/status");
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
                <DemoWorkspace onEvidence={refresh} />
                <section className="admin-card">
                  <h2>Demo diagnostics</h2>
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
                      Run paid preflight
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
                            {e.scenario} · {String(e.decision.decision)} ·{" "}
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
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}
