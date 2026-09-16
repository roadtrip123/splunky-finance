import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Splunky Finance — Banking with clarity",
  description: "A fictional Australian banking demonstration.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en-AU">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
