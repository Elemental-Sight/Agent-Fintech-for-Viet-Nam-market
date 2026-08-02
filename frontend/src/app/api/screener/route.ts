import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

// Screening the whole curated universe (~20 tickers, sequential vnstock
// calls) can take well over a minute -- see PROJECT_CONTEXT.md. No
// artificial timeout here either.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const res = await backendFetch("/screener", { method: "POST", body: JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data, { status: res.status });
}
