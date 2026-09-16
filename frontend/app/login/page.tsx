import Link from "next/link";
import Brand from "@/components/Brand";
import Login from "@/components/Login";
export default function LoginPage() {
  return (
    <>
      <header className="public-header">
        <Brand />
        <Link href="/" className="text-link">
          ← Back to home
        </Link>
      </header>
      <main id="main" className="login-page">
        <div className="login-story">
          <div className="eyebrow">MORE CLARITY. EVERY DAY.</div>
          <h2>
            A moment for
            <br />
            your money.
          </h2>
          <p>
            Your accounts, your activity, and the answers you need.
            <br />
            Together in one place.
          </p>
          <div className="login-decoration" aria-hidden="true">
            ›
          </div>
        </div>
        <section className="login-box">
          <Login />
        </section>
      </main>
    </>
  );
}
