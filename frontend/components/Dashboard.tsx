"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Account, Transaction, api, money } from "@/lib/api";
export default function Dashboard() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [cash, setCash] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    Promise.all([
      api<{ items: Account[]; cash_total_cents: number }>("accounts"),
      api<{ items: Transaction[] }>(
        "accounts/everyday/transactions?page_size=6",
      ),
    ])
      .then(([a, t]) => {
        setAccounts(a.items);
        setCash(a.cash_total_cents);
        setTransactions(t.items);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">YOUR BANKING, AT A GLANCE</div>
        <h1>
          Hello, Alex<span className="green">.</span>
        </h1>
        <p className="muted">
          A clearer picture of where you are, and what’s next.
        </p>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">Loading your accounts…</p>
      ) : (
        <>
          <div className="overview-summary">
            <span className="mini-label">TOTAL CASH & SAVINGS</span>
            <strong>{money(cash)}</strong>
            <span className="muted">Posted balances · AUD</span>
            <span className="summary-decoration" aria-hidden="true">
              ↗
            </span>
          </div>
          <div className="section-heading compact">
            <h2>
              Your accounts <span className="count">3</span>
            </h2>
            <span className="muted">Everything in one place</span>
          </div>
          <div className="account-grid">
            {accounts.map((a) => (
              <Link
                href={`/banking/accounts/${a.id}`}
                key={a.id}
                className={`account-card ${a.type}`}
              >
                <div className="card-top">
                  <span className="product-icon" aria-hidden="true">
                    {a.type === "savings"
                      ? "↗"
                      : a.type === "credit_card"
                        ? "▤"
                        : "◈"}
                  </span>
                  <span aria-hidden="true">↗</span>
                </div>
                <h3>{a.name}</h3>
                <span className="muted">{a.masked_number}</span>
                <strong>
                  {money(
                    a.type === "credit_card"
                      ? Math.max(0, -a.posted_balance_cents)
                      : a.posted_balance_cents,
                  )}
                </strong>
                <span className="mini-label">
                  {a.type === "credit_card" ? "AMOUNT OWED" : "POSTED BALANCE"}
                </span>
              </Link>
            ))}
          </div>
          <div className="section-heading compact">
            <h2>Recent activity</h2>
            <Link className="text-link" href="/banking/accounts/everyday">
              View Everyday history ↗
            </Link>
          </div>
          <div className="table-card">
            <table>
              <thead>
                <tr>
                  <th>Transaction</th>
                  <th>Date</th>
                  <th>Status</th>
                  <th className="right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <span className="merchant">{t.merchant}</span>
                      <small>{t.category}</small>
                    </td>
                    <td>
                      {new Date(t.posted_date + "T12:00:00").toLocaleDateString(
                        "en-AU",
                        { day: "numeric", month: "short" },
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
          </div>
        </>
      )}
    </>
  );
}
