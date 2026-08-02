import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET() {
  const res = await backendFetch("/observability");
  return NextResponse.json(await res.json(), { status: res.status });
}
