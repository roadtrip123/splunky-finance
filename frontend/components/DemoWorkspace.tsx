"use client";
import { useEffect, useRef, useState } from "react";
import { api, mutate } from "@/lib/api";

type Run = { id: string; scenario: string; protection: boolean; revision: number };
type Scenario = { prompt: string; prompts?: string[]; protection_applicable: boolean };
type Status = { banking_connection: { state: string; session: string | null }; run: Run | null; scenarios: Record<string, Scenario>; protection_status: string; demo_mode: "presenter" | "workshop"; galileo: { enabled: boolean; connection: string } };
type Answer = { answer: string; conversation_id: string; scenario: string; protection_enabled: boolean; protection_decision: { decision?: string }; };
type Entry = { question: string; result: Answer };
const descriptions: Record<string, [string, string]> = {
  normal_spending: ["Normal Answers", "Answers use the banking tools without a deliberate fault."],
  incomplete_answer: ["Incomplete Answer", "Deliberately omits important details from the answer to your question."],
  incorrect_total: ["Incorrect Total", "Introduces a wrong amount or numerical claim related to your question."],
  wrong_customer: ["Wrong Customer", "Answers as if you were Dan Whitfield, a real other customer, and discloses his real balance."],
  money_transfer: ["Guardrail Cross-Customer Access", "Blocks transfers to, and balance checks on, another customer's account before either tool runs. Your own accounts keep working. With it off, the transfer executes and the balance is disclosed."],
};
const label = (key: string) => descriptions[key]?.[0] || key;
function decision(result: Answer) {
  if (!result.protection_enabled) return "Protection off";
  switch (result.protection_decision.decision) {
    case "allow": return "Allowed by protection";
    case "deny": return "Blocked by protection";
    default: return "Could not be checked — fallback delivered";
  }
}
export default function DemoWorkspace({ onEvidence }: { onEvidence: () => Promise<void> }) {
  const [pairing, setPairing] = useState<{ code: string; expires_at: number }>();
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false);
  const active = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [conversation, setConversation] = useState<string>();
  const current = useRef<Run | null>(null);
  async function refresh() {
    const next = await api<Status>("demo-admin/status");
    if (!next.run) next.run = await mutate<Run>("demo-admin/workspace", {}, true);
    if (current.current && (current.current.id !== next.run.id || current.current.revision !== next.run.revision)) {
      setConversation(undefined);
    }
    current.current = next.run;
    setStatus(next);
    return next;
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    const timer = setInterval(() => {
      if (!active.current) refresh().catch((e) => setError(e.message));
    }, 1500);
    return () => clearInterval(timer);
  }, []);
  async function select(scenario: string, protection: boolean) {
    if (!status?.run || active.current) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const run = await mutate<Run>("demo-admin/workspace", {
        scenario, protection, run_id: status.run.id, expected_revision: status.run.revision,
      }, true, "PUT");
      current.current = run;
      setStatus({ ...status, run });
      setConversation(undefined);
      setNotice(`${label(scenario)} enabled. Protection ${protection ? "on" : "off"}. Saved for your next message. Check the banking connection confirmation below.`);
      await onEvidence();
    } catch (e) {
      setError((e as Error).message);
      await refresh().catch(() => {});
    } finally { active.current = false; setBusy(false); }
  }
  async function send(question: string) {
    if (!status?.run || active.current || !question.trim()) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await mutate<Answer>("demo-admin/chat", {
        message: question, conversation_id: conversation,
        run_id: status.run.id, expected_revision: status.run.revision,
      }, true);
      setEntries((old) => [...old, { question, result }]);
      setConversation(result.conversation_id);
      setInput("");
      await onEvidence();
    } catch (e) {
      setError((e as Error).message);
      await refresh().catch(() => {});
    } finally { active.current = false; setBusy(false); }
  }
  const run = status?.run;
  const scenario = run && status?.scenarios[run.scenario];
  const protectionReady = status?.galileo.enabled && status.galileo.connection === "connected" && status.protection_status === "verified";
  return <section className="admin-card demo-workspace" aria-label="Demo chat workspace">
    <h2>Choose what to demonstrate</h2>
    <p>These controls apply to your connected banking session and the demo chat below. Other sessions remain independent.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="notice">{notice}</p>}
    {!run ? <p role="status">Connecting your demo chat…</p> : <>
      <div className="prompt-box">
        <h3>Banking connection</h3>
        <p role="status">{status?.banking_connection.state === "applied" ? "Applied to connected banking session" : status?.banking_connection.state === "updating" ? "Applying settings to banking session…" : status?.banking_connection.state === "waiting" ? "Waiting for banking chat to acknowledge settings — open My Bank Agent" : status?.banking_connection.state === "disconnected" ? "Banking session disconnected or expired" : (status?.demo_mode === "workshop" ? "No banking session connected. Open banking in another tab of this browser." : "No banking session connected. Open banking in this browser, or pair another computer.")}</p>
        {status?.banking_connection.session && <p>Session: {status.banking_connection.session}</p>}
        {!status?.banking_connection.session && status?.demo_mode !== "workshop" && <button className="button outline small" disabled={busy} onClick={async () => {
          try { setPairing(await mutate("demo-admin/pairing", {}, true)); setError(""); }
          catch (e) { setError((e as Error).message); }
        }}>Connect using pairing code</button>}
        {pairing && !status?.banking_connection.session && <p>Pairing code: <strong data-testid="pairing-code">{pairing.code}</strong> · Expires {new Date(pairing.expires_at * 1000).toLocaleTimeString()}. Enter it under Demo connection in My Bank Agent.</p>}
        {status?.banking_connection.session && <button className="text-button" disabled={busy} onClick={async () => {
          try { await mutate("demo-admin/disconnect", {}, true); setPairing(undefined); await refresh(); }
          catch (e) { setError((e as Error).message); }
        }}>Disconnect banking session</button>}
      </div>
      <div className="demo-scenarios">
        {Object.entries(status!.scenarios).map(([key]) => <button key={key}
          className={`button ${run.scenario === key ? "" : "outline"}`}
          aria-pressed={run.scenario === key} disabled={busy}
          onClick={() => select(key, status!.scenarios[key].protection_applicable)}>
          {key === "normal_spending" ? "Normal Answers" : `Enable ${label(key)}`}
        </button>)}
      </div>
      <p className="notice" aria-live="polite"><strong>Scenario: {label(run.scenario)}</strong> · Applied to your next demo message</p>
      <p>{descriptions[run.scenario]?.[1]}</p>
      {run.protection && (
        <p className="notice"><strong>Guardrail armed</strong> · {protectionReady ? "previously verified" : "not yet verified — the response will show the actual outcome"}</p>
      )}
      <h3>Demo chat</h3>
      <p>No customer login or session linking is needed.</p>
      <div className="prompt-box"><strong>Questions for this scenario — or ask your own</strong>
        {(scenario?.prompts?.length ? scenario.prompts : [scenario?.prompt ?? ""]).map((q, i) => (
          <div key={i} className="scenario-question">
            <p>{q}</p>
            <button className="button small" disabled={busy} onClick={() => send(q)}>Run</button>
          </div>
        ))}
      </div>
      <div className="demo-transcript" aria-live="polite">
        {entries.map((entry, i) => <article key={i} className="demo-response">
          <p><strong>You:</strong> {entry.question}</p>
          <p className="badge">Scenario used: {label(entry.result.scenario)} · {decision(entry.result)}</p>
          <p style={{ whiteSpace: "pre-wrap" }}>{entry.result.answer}</p>
        </article>)}
      </div>
      {busy && <p role="status">Applying settings or preparing your answer…</p>}
      <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <label htmlFor="demo-message">Ask My Bank Agent</label>
        <textarea id="demo-message" value={input} maxLength={3000} disabled={busy}
          onChange={(e) => setInput(e.target.value)} placeholder="Ask about the synthetic banking data…" />
        <div className="admin-actions">
          <button className="button small" disabled={busy || !input.trim()}>Send message</button>
          <button type="button" className="button outline small" disabled={busy}
            onClick={() => { setConversation(undefined); setNotice("Fresh conversation ready. Your scenario settings remain active."); }}>New conversation</button>
        </div>
      </form>
    </>}
  </section>;
}
