import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await backendFetch(`/usage/${id}`);
  return NextResponse.json(await res.json(), { status: res.status });
}
