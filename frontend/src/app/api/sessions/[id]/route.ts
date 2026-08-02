import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await backendFetch(`/sessions/${id}`, { method: "DELETE" });
  return NextResponse.json(await res.json(), { status: res.status });
}

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  const res = await backendFetch(`/sessions/${id}`, { method: "PATCH", body });
  return NextResponse.json(await res.json(), { status: res.status });
}
