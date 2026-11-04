// Server-only FastAPI helpers: adds X-API-Key + Bearer, throws ApiError.
import { cookies } from "next/headers";

const BACKEND = process.env.BACKEND_URL!;
const KEY = process.env.BACKEND_API_KEY ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get("session")?.value;
}

export async function api(path: string, init?: RequestInit, token?: string) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (KEY) headers["X-API-Key"] = KEY;
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND}${path}`, {
    ...init,
    headers: { ...headers, ...((init?.headers as Record<string, string>) ?? {}) },
    cache: "no-store",
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data?.error?.message ?? "request failed");
  return data;
}

// Multipart POST (photo/plan upload): no JSON content type.
export async function postForm(path: string, form: FormData, token?: string) {
  const headers: Record<string, string> = {};
  if (KEY) headers["X-API-Key"] = KEY;
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND}${path}`, {
    method: "POST",
    headers,
    body: form,
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data?.error?.message ?? "request failed");
  return data;
}
