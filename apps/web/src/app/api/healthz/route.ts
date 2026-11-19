import { NextResponse } from "next/server";

export async function GET() {
  const backendUrl = (process.env.INTERNAL_API_URL || "http://127.0.0.1:8008").replace(/\/+$/, "");
  try {
    const res = await fetch(`${backendUrl}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) {
      return NextResponse.json({ status: "error", code: res.status }, { status: res.status });
    }
    const data: unknown = await res.json();
    if (typeof data !== "object" || data === null || !("status" in data) || data.status !== "ok") {
      return NextResponse.json({ status: "error", message: "Backend unavailable" }, { status: 502 });
    }
    return NextResponse.json({ status: "ok" });
  } catch {
    return NextResponse.json({ status: "error", message: "Backend unavailable" }, { status: 502 });
  }
}
