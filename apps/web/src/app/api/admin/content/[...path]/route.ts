import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };
const identifier = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const item = `(?:books|units)/${identifier}`;
const actions = "(?:submit|approve|publish|archive|reject)";

function permitted(method: string, path: string): boolean {
  if (method === "GET") {
    return new RegExp(`^(?:books|${item}(?:/audit)?|books/${identifier}/units)$`).test(path);
  }
  if (method === "POST") {
    return new RegExp(`^(?:books|units|${item}/${actions})$`).test(path);
  }
  return method === "PATCH" && new RegExp(`^${item}$`).test(path);
}

function json(data: unknown, status = 200) {
  return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

async function proxy(request: Request, context: RouteContext) {
  const key = request.headers.get("X-Admin-Api-Key");
  if (!key || key.length > 8192) return json({ detail: "Administrator credentials are required." }, 401);
  const { path } = await context.params;
  const relative = path.join("/");
  if (!permitted(request.method, relative)) return json({ detail: "Content endpoint not found." }, 404);
  if (request.method !== "GET" && request.headers.get("origin") !== new URL(request.url).origin) {
    return json({ detail: "Requests must come from this application." }, 403);
  }

  const backendUrl = (process.env.INTERNAL_API_URL || "http://127.0.0.1:8008").replace(/\/+$/, "");
  try {
    let body: string | undefined;
    if (request.method !== "GET") {
      body = await request.text();
      if (body.length > 65536) return json({ detail: "Content metadata is too large." }, 413);
      try { JSON.parse(body); } catch { return json({ detail: "A JSON body is required." }, 400); }
    }
    const response = await fetch(`${backendUrl}/admin/content/${relative}`, {
      method: request.method,
      headers: { "X-Admin-Api-Key": key, "Content-Type": "application/json" },
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10000),
    });
    if (response.status >= 500) return json({ detail: "Content service unavailable." }, 502);
    const data: unknown = await response.json();
    if (!response.ok) {
      const detail = typeof data === "object" && data !== null && "detail" in data ? data.detail : null;
      // Validation inputs and private upstream diagnostics must not be reflected.
      return json({ detail: typeof detail === "string" ? detail : "Check the content fields and try again." }, response.status);
    }
    return json(data, response.status);
  } catch {
    return json({ detail: "Content service unavailable." }, 502);
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
