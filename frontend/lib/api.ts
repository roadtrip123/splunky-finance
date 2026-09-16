export type Account = {
  id: string;
  name: string;
  type: string;
  masked_number: string;
  posted_balance_cents: number;
  credit_limit_cents: number | null;
};
export type Transaction = {
  id: string;
  account_id: string;
  posted_date: string;
  merchant: string;
  category: string;
  amount_cents: number;
  status: string;
  movement_type: string;
};
export type Session = { authenticated: boolean; csrf_token: string | null };
export type Citation = {
  citation: string;
  title: string;
  excerpt: string;
  section: string;
};
export function money(cents: number) {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
  }).format(cents / 100);
}
export async function api<T = Record<string, unknown>>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  const payload = await response.json();
  if (!response.ok)
    throw new Error(
      payload.error?.message || "Service temporarily unavailable",
    );
  return payload;
}
export async function mutate<T = Record<string, unknown>>(
  path: string,
  body: unknown = {},
  admin = false,
  method = "POST",
) {
  const session = await api<Session>(
    admin ? "demo-admin/session" : "auth/session",
  );
  return api<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: { "X-CSRF-Token": session.csrf_token || "" },
  });
}
