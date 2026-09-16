"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
export default function Login({
  admin = false,
  onSuccess,
}: {
  admin?: boolean;
  onSuccess?: () => void;
}) {
  const router = useRouter();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api(admin ? "demo-admin/login" : "auth/login", {
            method: "POST",
            body: JSON.stringify({ account_number: account, password }),
          });
          if (!admin) {
            if (remember) localStorage.setItem("splunky-account", account);
            else localStorage.removeItem("splunky-account");
          }
          setPassword("");
          if (onSuccess) onSuccess();
          else {
            router.push("/banking");
            router.refresh();
          }
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="eyebrow">
        {admin ? "PRESENTER ACCESS" : "WELCOME BACK"}
      </div>
      <h1 className="login-title">
        {admin ? "Demo administration" : "Your banking, in view."}
      </h1>
      <p className="muted">
        {admin
          ? "Sign in with your separate presenter credentials."
          : "Log in to your Splunky Finance accounts."}
      </p>
      {!admin && (
        <>
          <label htmlFor="account">Account number</label>
          <input
            id="account"
            autoComplete="username"
            inputMode="numeric"
            required
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            onFocus={() => {
              if (!account) {
                const saved = localStorage.getItem("splunky-account");
                if (saved) {
                  setAccount(saved);
                  setRemember(true);
                }
              }
            }}
          />
        </>
      )}
      <label htmlFor={admin ? "admin-password" : "password"}>Password</label>
      <div className="password-input">
        <input
          id={admin ? "admin-password" : "password"}
          type={visible ? "text" : "password"}
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          aria-pressed={visible}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {!admin && (
        <div className="login-options">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />{" "}
            Remember account number
          </label>
          <button
            type="button"
            className="text-button"
            onClick={() =>
              setInfo(
                "Password recovery is unavailable in this fictional demo. Ask the presenter for the configured demo credentials.",
              )
            }
          >
            Forgot password?
          </button>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {info && (
        <p className="notice" role="status">
          {info}
        </p>
      )}
      <button className="button full" disabled={busy}>
        {busy ? "Logging in…" : "Log in"} ↗
      </button>
      <p className="fine-print">
        {admin
          ? "Presenter controls are separate from customer banking."
          : "Fictional demo. Please do not enter real banking credentials."}
      </p>
    </form>
  );
}
