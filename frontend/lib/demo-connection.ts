"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
export type Preset = { id: string; label: string; note: string; group?: string; scenario: string; protection: boolean; prompt: string | null };
export type DemoState = { version: string; scenario: string; connected: boolean; expired: boolean;
  protection?: boolean; demo_chip?: boolean; presets?: Preset[] };
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
  // Identifies which sync owns `pending`, so a superseded one does not clear its replacement's slot.
  const owner = useRef<object | null>(null);
  // `force` skips the in-flight request rather than awaiting it. The poll below runs every second,
  // so a caller that has just changed the demo settings would otherwise be handed the answer to a
  // request made *before* that change, send the stale version, and get a 409 back.
  async function sync(force = false): Promise<DemoState> {
    if (pending.current && !force) return pending.current;
    const token = {};
    const mine: Promise<DemoState> = (async () => {
      try {
        const next = await demoRequest<DemoState>("chat/demo-sync");
        if (alive.current) setState(next);
        // Advisory: it tells the portal the banking session has caught up. A 409 here means a
        // newer version already exists, which the next poll acknowledges, so it is not an error
        // for the caller and must not take `ready` down with it.
        try {
          await demoRequest("chat/demo-ack", { version: next.version });
        } catch {
          /* superseded */
        }
        if (alive.current) setReady(!next.expired);
        return next;
      } catch (e) {
        if (alive.current) setReady(false);
        throw e;
      } finally {
        if (owner.current === token) {
          owner.current = null;
          pending.current = null;
        }
      }
    })();
    owner.current = token;
    pending.current = mine;
    return mine;
  }
  useEffect(() => {
    alive.current = visible;
    if (!visible) return;
    setReady(false);
    sync().catch(() => {});
    const timer = setInterval(() => sync().catch(() => {}), 1000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [visible]);
  // "Normal answers" and "nothing I do in the portal will reach this tab" used to look identical,
  // because both reported scenario normal_spending. They are completely different situations, and
  // the second one cost a round of testing: a preset armed a run this session was not attached to,
  // and the only indicator a presenter watches said everything was fine.
  const description = !ready
    ? state?.expired
      ? "Demo session expired. Disconnect or pair again."
      : "Synchronizing demo settings or reconnecting…"
    : !state?.connected
      ? "Not connected to presenter controls: scenarios will not apply"
      : state?.scenario === "normal_spending"
        ? "Normal answers"
        : `${state?.scenario.replaceAll("_", " ")} enabled`;
  const tone = !ready
    ? "pending"
    : !state?.connected
      ? "unlinked"
      : state?.scenario === "normal_spending"
        ? "normal"
        : "fault";
  return { state, ready, sync, description, tone };
}
