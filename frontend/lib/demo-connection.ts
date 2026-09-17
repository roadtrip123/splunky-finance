"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
export type DemoState = { version: string; scenario: string; connected: boolean; expired: boolean };
export async function demoRequest<T>(path: string, body: unknown = {}): Promise<T> {
  const session = await api<{ csrf_token: string }>("auth/session", { signal: AbortSignal.timeout(4000) });
  return api<T>(path, { method: "POST", body: JSON.stringify(body),
    headers: { "X-CSRF-Token": session.csrf_token }, signal: AbortSignal.timeout(4000) });
}
export function useDemoConnection(visible: boolean) {
  const [state, setState] = useState<DemoState>();
  const [ready, setReady] = useState(false);
  const alive = useRef(false);
  const pending = useRef<Promise<DemoState> | null>(null);
  async function sync(): Promise<DemoState> {
    if (pending.current) return pending.current;
    pending.current = (async () => {
      try {
        const next = await demoRequest<DemoState>("chat/demo-sync");
        if (alive.current) setState(next);
        await demoRequest("chat/demo-ack", { version: next.version });
        if (alive.current) setReady(!next.expired);
        return next;
      } catch (e) {
        if (alive.current) setReady(false);
        throw e;
      } finally { pending.current = null; }
    })();
    return pending.current;
  }
  useEffect(() => {
    alive.current = visible;
    if (!visible) return;
    setReady(false);
    sync().catch(() => {});
    const timer = setInterval(() => sync().catch(() => {}), 1000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [visible]);
  const description = !ready ? state?.expired ? "Demo session expired. Disconnect or pair again." : "Synchronizing demo settings or reconnecting…"
    : state?.scenario === "normal_spending" ? "Normal answers" : `${state?.scenario.replaceAll("_", " ")} enabled`;
  const tone = !ready ? "pending" : state?.scenario === "normal_spending" ? "normal" : "fault";
  return { state, ready, sync, description, tone };
}
