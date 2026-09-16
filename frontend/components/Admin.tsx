"use client";
import Link from "next/link";
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
  replayed: boolean;
  source_run_id: string | null;
  decision: Record<string, unknown>;
  evaluation: Record<string, unknown>;
};
type Status = {
  provider: string;
  model: string;
  provider_status: { state: string };
  galileo: { state: string; export: string; last_error: string | null };
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
  const run = status?.run;
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
                Customer banking stays separate.
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
                    <h3>{status.galileo.state}</h3>
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
                  </article>
                </div>
                <section className="admin-card">
                  <div className="section-heading compact">
                    <h2>Presenter run</h2>
                    <button
                      disabled={busy}
                      className="button small"
                      onClick={() =>
                        action(() => mutate("demo-admin/run", {}, true))
                      }
                    >
                      Start a new run
                    </button>
                  </div>
                  {run ? (
                    <>
                      <p className="mono">{run.id}</p>
                      <div className="admin-controls">
                        <div>
                          <label htmlFor="scenario">Scenario</label>
                          <select
                            id="scenario"
                            value={run.scenario}
                            disabled={busy}
                            onChange={(e) =>
                              action(() =>
                                mutate(
                                  "demo-admin/scenario",
                                  {
                                    run_id: run.id,
                                    scenario_id: e.target.value,
                                    expected_revision: run.revision,
                                  },
                                  true,
                                  "PUT",
                                ),
                              )
                            }
                          >
                            {Object.keys(status.scenarios).map((s) => (
                              <option key={s}>{s}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label htmlFor="protection">Output protection</label>
                          <select
                            id="protection"
                            value={String(run.protection)}
                            disabled={busy}
                            onChange={(e) =>
                              action(() =>
                                mutate(
                                  "demo-admin/protection",
                                  {
                                    run_id: run.id,
                                    enabled: e.target.value === "true",
                                    expected_revision: run.revision,
                                  },
                                  true,
                                  "PUT",
                                ),
                              )
                            }
                          >
                            <option value="false">Disabled</option>
                            <option value="true">Enabled — fail closed</option>
                          </select>
                        </div>
                        <button
                          className="button outline small"
                          disabled={busy}
                          onClick={() =>
                            action(async () => {
                              await mutate("demo-admin/bind", {
                                token: run.binding,
                              });
                              setNotice(
                                "Run linked to the customer session in this browser. Open banking in another tab.",
                              );
                            })
                          }
                        >
                          Link customer session
                        </button>
                        <Link
                          href="/banking"
                          target="_blank"
                          className="text-link"
                        >
                          Open banking ↗
                        </Link>
                      </div>
                      <p className="notice">
                        Protection verification: {status.protection_status}.
                        Enabling the switch does not prove a live control has
                        run.
                      </p>
                      <div className="prompt-box">
                        <span className="mini-label">DEMO PROMPT</span>
                        <p>{status.scenarios[run.scenario].prompt}</p>
                        <button
                          className="text-button"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(
                                status.scenarios[run.scenario].prompt,
                              );
                              setNotice("Prompt copied.");
                            } catch {
                              setNotice("Select and copy the prompt above.");
                            }
                          }}
                        >
                          Copy prompt
                        </button>
                      </div>
                      <p className="fine-print">
                        Fault scenarios deliberately inject the candidate after
                        the live model call. Before/after replays the same
                        candidate; traces label both behaviours.
                      </p>
                    </>
                  ) : (
                    <p className="muted">
                      Create a run, log in to customer banking in this browser,
                      then link the customer session.
                    </p>
                  )}
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
                      disabled={busy}
                      onClick={() =>
                        action(() => mutate("demo-admin/reset", {}, true))
                      }
                    >
                      Reset run
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
                  <h2>Latest run evidence</h2>
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
                      No runs observed yet. No scores or decisions are
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
                            {e.replayed
                              ? "candidate replay"
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
                                source_run_id: e.source_run_id,
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
