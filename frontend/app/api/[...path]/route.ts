import { NextRequest } from "next/server";
export const runtime = "nodejs";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (!path.every((x) => /^[a-zA-Z0-9_-]+$/.test(x)))
    return Response.json(
      { error: { message: "Invalid path" } },
      { status: 400 },
    );
  const headers = new Headers();
  for (const name of ["cookie", "origin", "content-type", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const body = ["GET", "HEAD"].includes(request.method)
      ? undefined
      : await request.text();
    if (body && body.length > 16000)
      return Response.json(
        { error: { message: "Request too large" } },
        { status: 413 },
      );
    const result = await fetch(
      `${process.env.BACKEND_URL || "http://127.0.0.1:8001"}/api/${path.join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(120000),
      },
    );
    const out = new Headers({
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    });
    for (const cookie of result.headers.getSetCookie())
      out.append("Set-Cookie", cookie);
    const correlation = result.headers.get("x-correlation-id");
    if (correlation) out.set("x-correlation-id", correlation);
    return new Response(await result.text(), {
      status: result.status,
      headers: out,
    });
  } catch {
    return Response.json(
      { error: { message: "The banking service is temporarily unavailable" } },
      { status: 503 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PUT };
