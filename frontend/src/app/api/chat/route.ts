import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

// No client-side timeout override here -- company_evaluation questions fan
// out to 2 data sources + a Groq call (+ up to 1 guardrail retry) and can
// legitimately take 10-20s, sometimes more. Let it run.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const res = await backendFetch("/chat", { method: "POST", body: JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data, { status: res.status });
}
