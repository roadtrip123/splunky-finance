"use client";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState } from "react";
import Brand from "./Brand";
import Chat from "./Chat";
import { mutate } from "@/lib/api";
export default function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [chat, setChat] = useState(false);
  const [error, setError] = useState("");
  return (
    <>
      <header className="bank-header">
        <Brand />
        <nav aria-label="Banking navigation">
          <Link href="/banking" className={path === "/banking" ? "active" : ""}>
            Overview
          </Link>
          <button className="nav-button" onClick={() => setChat(true)}>
            My Bank Agent
          </button>
        </nav>
        <div className="header-user">
          <span className="avatar">AT</span>
          <span className="user-name">Alex Taylor</span>
          <button
            className="text-button"
            onClick={async () => {
              try {
                await mutate("auth/logout");
                router.push("/login");
                router.refresh();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Log out ↗
          </button>
        </div>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <main id="main" className="bank-main">
        {children}
      </main>
      <footer className="bank-footer">
        <span>Fictional demonstration accounts · AUD</span>
        <span>Splunky Finance</span>
      </footer>
      <button
        className="agent-launcher"
        onClick={() => setChat(true)}
        aria-label="Open My Bank Agent"
      >
        <span aria-hidden="true">✧</span> My Bank Agent
      </button>
      <Chat visible={chat} close={() => setChat(false)} />
    </>
  );
}
