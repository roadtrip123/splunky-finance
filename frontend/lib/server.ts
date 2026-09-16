import { cookies } from "next/headers";
import { redirect } from "next/navigation";
export async function requireCustomer() {
  const jar = await cookies();
  const value = jar.get("splunky_customer_session")?.value;
  if (!value) redirect("/login");
  let authenticated = false;
  try {
    const response = await fetch(
      `${process.env.BACKEND_URL || "http://127.0.0.1:8001"}/api/auth/session`,
      {
        headers: { Cookie: `splunky_customer_session=${value}` },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    authenticated = (await response.json()).authenticated;
  } catch {}
  if (!authenticated) redirect("/login");
}
