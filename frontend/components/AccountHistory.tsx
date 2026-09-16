"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Account, Transaction, api, money } from "@/lib/api";
export default function AccountHistory({ id }: { id: string }) {
  const [account, setAccount] = useState<Account>();
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("date_desc");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Account>(`accounts/${id}`)
      .then(setAccount)
      .catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    const query = new URLSearchParams({
      page: String(page),
      page_size: "15",
      sort,
    });
    if (start) query.set("start", start);
    if (end) query.set("end", end);
    if (category) query.set("category", category);
    if (search) query.set("search", search);
    const timeout = setTimeout(() => {
      api<{ items: Transaction[]; total: number }>(
        `accounts/${id}/transactions?${query}`,
      )
        .then((r) => {
          if (active) {
            setItems(r.items);
            setTotal(r.total);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setBusy(false);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [id, page, start, end, category, search, sort]);
  return (
    <>
      <Link href="/banking" className="text-link">
        ← All accounts
      </Link>
      <div className="page-heading">
        <div className="eyebrow">YOUR ACCOUNT</div>
        <h1>{account?.name || "Account history"}</h1>
        <p className="muted">{account?.masked_number} · AUD</p>
      </div>
      {account && (
        <div className="overview-summary">
          <span className="mini-label">
            {account.type === "credit_card" ? "AMOUNT OWED" : "POSTED BALANCE"}
          </span>
          <strong>
            {money(
              account.type === "credit_card"
                ? Math.max(0, -account.posted_balance_cents)
                : account.posted_balance_cents,
            )}
          </strong>
          {account.credit_limit_cents && (
            <span className="muted">
              Credit limit {money(account.credit_limit_cents)}
            </span>
          )}
          <span className="muted">
            Pending transactions shown separately below
          </span>
        </div>
      )}
      <div className="section-heading compact">
        <h2>Transaction history</h2>
        <span className="muted">{total} transactions</span>
      </div>
      <div className="filters">
        <div>
          <label htmlFor="search">Search merchants</label>
          <input
            id="search"
            type="search"
            maxLength={100}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Search transactions"
          />
        </div>
        <div>
          <label htmlFor="start">From (inclusive)</label>
          <input
            id="start"
            type="date"
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div>
          <label htmlFor="end">To (exclusive)</label>
          <input
            id="end"
            type="date"
            value={end}
            onChange={(e) => {
              setEnd(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div>
          <label htmlFor="category">Category</label>
          <select
            id="category"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All categories</option>
            {[
              "restaurants",
              "groceries",
              "shopping",
              "fuel",
              "utilities",
              "subscriptions",
              "rent",
              "insurance",
              "salary",
              "internal",
              "interest",
            ].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="sort">Sort by</label>
          <select
            id="sort"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(1);
            }}
          >
            <option value="date_desc">Newest first</option>
            <option value="date_asc">Oldest first</option>
            <option value="amount_desc">Amount: high to low</option>
            <option value="amount_asc">Amount: low to high</option>
          </select>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="table-card" aria-busy={busy}>
        {busy ? (
          <p className="table-state" role="status">
            Loading transactions…
          </p>
        ) : !items.length ? (
          <p className="table-state">No transactions match your filters.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Merchant / description</th>
                <th>Date</th>
                <th>Status</th>
                <th className="right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <span className="merchant">{t.merchant}</span>
                    <small>
                      {t.category} · {t.movement_type}
                    </small>
                  </td>
                  <td>
                    {new Date(t.posted_date + "T12:00:00").toLocaleDateString(
                      "en-AU",
                    )}
                  </td>
                  <td>
                    <span className={`badge ${t.status}`}>{t.status}</span>
                  </td>
                  <td
                    className={`right amount ${t.amount_cents > 0 ? "green" : ""}`}
                  >
                    {t.amount_cents > 0 ? "+" : ""}
                    {money(t.amount_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="pagination">
        <button
          className="button outline small"
          disabled={page === 1 || busy}
          onClick={() => setPage(page - 1)}
        >
          ← Previous
        </button>
        <span>
          Page {page} of {Math.max(1, Math.ceil(total / 15))}
        </span>
        <button
          className="button outline small"
          disabled={page * 15 >= total || busy}
          onClick={() => setPage(page + 1)}
        >
          Next →
        </button>
      </div>
    </>
  );
}
