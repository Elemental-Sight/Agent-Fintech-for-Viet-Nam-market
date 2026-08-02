import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET() {
  const res = await backendFetch("/sessions");
  return NextResponse.json(await res.json(), { status: res.status });
}

export async function POST() {
  const res = await backendFetch("/sessions", { method: "POST" });
  return NextResponse.json(await res.json(), { status: res.status });
}
