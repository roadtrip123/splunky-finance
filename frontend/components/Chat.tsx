"use client";
import { useEffect, useRef, useState } from "react";
import { Citation, mutate } from "@/lib/api";
import { useDemoConnection, demoRequest } from "@/lib/demo-connection";
type Message = {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  at: number;
  elapsedMs?: number;
};
const clock = (at: number) =>
  new Date(at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export default function Chat({
  close,
  visible,
}: {
  close: () => void;
  visible: boolean;
}) {
  const demo = useDemoConnection(visible);
  const [pairCode, setPairCode] = useState("");
  const [pairBusy, setPairBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [conversation, setConversation] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!visible) return;
    const before = document.activeElement;
    field.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (before instanceof HTMLElement) before.focus();
    };
  }, [visible]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);
  async function send(text: string) {
    if (!text.trim() || busy || !demo.ready || pairBusy) return;
    setError("");
    const sentAt = Date.now();
    setMessages((m) => [...m, { role: "user", text, at: sentAt }]);
    setBusy(true);
    try {
      const confirmed = await demo.sync();
      if (confirmed.expired) throw new Error("Demo session expired. Disconnect or pair again.");
      const result = await mutate<{
        answer: string;
        conversation_id: string;
        citations: Citation[];
      }>("chat", { message: text, conversation_id: conversation, demo_version: confirmed.version });
      setInput("");
      setConversation(result.conversation_id);
      const receivedAt = Date.now();
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: result.answer,
          citations: result.citations,
          at: receivedAt,
          elapsedMs: receivedAt - sentAt,
        },
      ]);
    } catch (e) {
      setError((e as Error).message);
      await demo.sync().catch(() => {});
    } finally {
      setBusy(false);
      field.current?.focus();
    }
  }
  if (!visible) return null;
  return (
    <div
      className="drawer-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        ref={panel}
        className="chat-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") close();
          if (e.key === "Tab") {
            const nodes = panel.current?.querySelectorAll<HTMLElement>(
              "button:not(:disabled), textarea, input, a[href]",
            );
            if (nodes?.length) {
              const first = nodes[0],
                last = nodes[nodes.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
              }
            }
          }
        }}
      >
        <div className="chat-heading">
          <div>
            <span className="agent-icon">✧</span>
            <h2 id="chat-title">My Bank Agent</h2>
            <span className="muted">A clearer view of your banking</span>
          </div>
          <button
            className="icon-button"
            onClick={close}
            aria-label="Close My Bank Agent"
          >
            ×
          </button>
        </div>
        <div className="chat-messages">
          {!messages.length && (
            <div className="chat-welcome">
              <div className="welcome-symbol" aria-hidden="true">
                ✧
              </div>
              <h3>What’s on your mind?</h3>
              <p>
                I can help you explore your accounts, understand your spending,
                and find bank policy answers.
              </p>
              {[
                "How much did I spend on restaurants last month?",
                // Matches the Incomplete Answer scenario prompt, so a presenter can click rather
                // than type it. The three-part version it replaced is still a fine question, but
                // the scenario no longer uses it and the two have to match to demo cleanly.
                "How much did I spend on restaurants last month and what was the largest purchase?",
                "What are my account balances?",
                "What is the balance of account number 1234?",
                "What is the Everyday account monthly fee?",
              ].map((text) => (
                <button
                  className="suggestion"
                  key={text}
                  onClick={() => send(text)}
                  disabled={busy || !demo.ready || pairBusy}
                >
                  {text} ↗
                </button>
              ))}
            </div>
          )}
          {messages.map((message, index) => (
            <div key={index} className={`message ${message.role}`}>
              <span className="message-label">
                {message.role === "user" ? "YOU" : "MY BANK AGENT"}
                <time className="message-time" dateTime={new Date(message.at).toISOString()}>
                  {clock(message.at)}
                  {message.elapsedMs !== undefined &&
                    ` · ${(message.elapsedMs / 1000).toFixed(1)}s`}
                </time>
              </span>
              <p>{message.text}</p>
              {message.citations?.map((c) => (
                <details key={c.citation}>
                  <summary>
                    {c.title} · {c.section}
                  </summary>
                  <p>{c.excerpt}</p>
                </details>
              ))}
            </div>
          ))}
          {busy && (
            <div className="processing" role="status">
              Checking your banking information…
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div ref={bottom} />
        </div>
        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <label htmlFor="chat-message" className="sr-only">
            Ask My Bank Agent
          </label>
          <textarea
            ref={field}
            id="chat-message"
            placeholder="Ask about your banking…"
            maxLength={3000}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <button
            className="button small"
            disabled={busy || !demo.ready || pairBusy || !input.trim()}
            aria-label="Send message"
          >
            ↑
          </button>
          <div className="chat-input-footer">
            <button
              type="button"
              className="text-button"
              disabled={busy || !demo.ready || pairBusy}
              onClick={async () => {
                try {
                  await mutate("chat/reset");
                  setMessages([]);
                  setConversation(undefined);
                  setError("");
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              New conversation
            </button>
            <span className={`demo-footer demo-footer-${demo.tone}`} title={demo.description} aria-label={`Fictional banking data only. ${demo.description}`}>Fictional banking data only</span>
          </div>
        </form>
        <details className="demo-pairing">
          <summary>Demo connection</summary>
          <p>{demo.state?.connected ? "Connected to presenter controls." : "Same-browser linking is automatic. For another computer, enter the presenter’s pairing code."}</p>
          <label htmlFor="demo-pair-code">Pairing code</label>
          <input id="demo-pair-code" value={pairCode} maxLength={32} onChange={(e) => setPairCode(e.target.value)} />
          <button type="button" className="text-button" disabled={busy || pairBusy || !pairCode.trim()} onClick={async () => {
            setPairBusy(true); setError("");
            try { await demoRequest("chat/demo-pair", { code: pairCode }); setPairCode(""); await demo.sync(); }
            catch (e) { setError((e as Error).message); }
            finally { setPairBusy(false); }
          }}>Connect demo</button>
          <button type="button" className="text-button" disabled={busy || pairBusy} onClick={async () => {
            setPairBusy(true); setError("");
            try { await demoRequest("chat/demo-disconnect"); await demo.sync(); }
            catch (e) { setError((e as Error).message); }
            finally { setPairBusy(false); }
          }}>Disconnect demo</button>
        </details>
      </div>
    </div>
  );
}
