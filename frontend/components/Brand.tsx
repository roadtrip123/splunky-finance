import Link from "next/link";
export default function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Splunky Finance home">
      <span className="brand-mark" aria-hidden="true">
        ›
      </span>
      <span>
        splunky<span className="brand-finance">finance</span>
      </span>
    </Link>
  );
}
