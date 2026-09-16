import Link from "next/link";
import Brand from "@/components/Brand";
export default function Home() {
  return (
    <>
      <header className="public-header">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#accounts">Our accounts</a>
          <a href="#security">Your security</a>
          <Link className="button outline small" href="/login">
            Log in ↗
          </Link>
        </nav>
      </header>
      <main id="main">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="status-dot" /> A little more clarity. A lot more
              possibility.
            </div>
            <h1>
              Your money.
              <br />
              Your next move.
              <br />
              <span>All in view.</span>
            </h1>
            <p>
              Everyday banking that makes sense. Bring your accounts together
              and find a clearer picture of your money.
            </p>
            <div className="hero-actions">
              <Link href="/login" className="button">
                Explore your banking ↗
              </Link>
              <a className="text-link" href="#accounts">
                Find your account ↓
              </a>
            </div>
            <div className="hero-note">◈ Made for life in Australia</div>
          </div>
          <div
            className="hero-art"
            aria-label="Illustration of fictional accounts"
          >
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="art-label">A clearer picture</div>
            <div className="art-card savings-art">
              <span className="mini-label">YOUR NEXT CHAPTER</span>
              <div className="art-symbol">↗</div>
              <h3>Savings</h3>
              <p>Space for something bigger.</p>
              <div className="mini-chart">▂ ▃ ▃ ▅ ▄ ▆ ▆ █</div>
            </div>
            <div className="art-card everyday-art">
              <div className="card-top">
                <span>splunky finance</span>
                <span>◈</span>
              </div>
              <span className="mini-label">EVERYDAY POSSIBILITIES</span>
              <h3>Everyday</h3>
              <div className="art-card-bottom">
                <span>•••• 1042</span>
                <span>Alex Taylor</span>
              </div>
            </div>
            <div className="art-pill">
              <span className="status-dot" /> One place. More perspective.
            </div>
          </div>
        </section>
        <section className="benefit-strip">
          <div>
            <span>01</span> Simple by design
          </div>
          <div>
            <span>02</span> A view of every account
          </div>
          <div>
            <span>03</span> Answers when you need them
          </div>
        </section>
        <section id="accounts" className="products section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">BANKING, WITH ROOM TO GROW</div>
              <h2>Built around your everyday.</h2>
            </div>
            <p>
              From the weekly shop to your next big plan,
              <br />
              find an account for the way you live.
            </p>
          </div>
          <div className="product-grid">
            {[
              [
                "01",
                "Everyday",
                "For the money that keeps life moving.",
                "$0",
                "monthly account fee",
              ],
              [
                "02",
                "Savings",
                "A little space for your future plans.",
                "2.00%",
                "fictional interest p.a.",
              ],
              [
                "03",
                "Credit Card",
                "A clear view of spending and repayments.",
                "$0",
                "annual card fee",
              ],
            ].map(([number, name, description, value, label]) => (
              <article className="product-card" key={name}>
                <div className="card-top">
                  <span className="mini-label">{number} / YOUR MONEY</span>
                  <span className="product-icon" aria-hidden="true">
                    {name === "Savings"
                      ? "↗"
                      : name === "Credit Card"
                        ? "▤"
                        : "◈"}
                  </span>
                </div>
                <h3>{name}</h3>
                <p>{description}</p>
                <div className="product-value">
                  {value}
                  <small>{label}</small>
                </div>
                <Link href="/login" className="text-link">
                  Explore in the demo ↗
                </Link>
              </article>
            ))}
          </div>
          <p className="fine-print">
            All rates, fees, accounts and customer information are fictional
            demonstration examples.
          </p>
        </section>
        <section className="security-section section" id="security">
          <div className="security-icon" aria-hidden="true">
            ◈
          </div>
          <div>
            <div className="eyebrow">PEACE OF MIND, EVERY DAY</div>
            <h2>Good banking starts with trust.</h2>
            <p>
              Keep your passwords and verification codes private. Use your
              bank’s official contact channels when something doesn’t feel
              right.
            </p>
          </div>
          <Link href="/login" className="button outline">
            View your accounts ↗
          </Link>
        </section>
      </main>
      <footer>
        <Brand />
        <p>
          A fictional banking demo. No real banking services.
          <br />
          Not affiliated with or endorsed by Splunk.
        </p>
        <span>© 2026 Splunky Finance</span>
      </footer>
    </>
  );
}
