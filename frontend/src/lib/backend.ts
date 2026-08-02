/**
 * Server-side-only helper for talking to the FastAPI backend. `BACKEND_URL`
 * (e.g. "http://app:8000" inside Docker Compose) only resolves on the
 * Docker network, never from the user's browser -- every Route Handler in
 * `app/api/*` proxies through this instead of the browser calling FastAPI
 * directly, mirroring how the old Streamlit UI called it via `requests`
 * from its own server-side Python process.
 */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export class BackendError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`Backend responded with ${status}`);
    this.status = status;
    this.body = body;
  }
}

export async function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
}

export async function backendJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await backendFetch(path, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new BackendError(res.status, body);
  }
  return body as T;
}
