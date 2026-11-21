import type { z } from "zod";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";
const TOKEN_KEY = "iiq.token";

// Central session handling: the token lives in sessionStorage only (cleared with the tab).
type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();

export const session = {
  get token(): string | null {
    return sessionStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    sessionStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
  },
  onUnauthorized(fn: Listener) {
    unauthorizedListeners.add(fn);
    return () => {
      unauthorizedListeners.delete(fn);
    };
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get isStale() {
    return this.code === "STALE_VERSION" || this.status === 409;
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions<S extends z.ZodTypeAny> {
  method?: "GET" | "POST";
  body?: unknown;
  query?: Query;
  schema?: S;
  auth?: boolean;
}

export async function request<S extends z.ZodTypeAny>(
  path: string,
  opts: RequestOptions<S> = {},
): Promise<z.infer<S>> {
  const url = new URL(BASE + path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = session.token;
  if (token && opts.auth !== false) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the API. Is the backend running?");
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const env = (data as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | null)
      ?.error;
    if (res.status === 401 && opts.auth !== false) {
      session.clear();
      unauthorizedListeners.forEach((fn) => fn());
    }
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(
      res.status,
      env?.code ?? `HTTP_${res.status}`,
      env?.message ?? (typeof detail === "string" ? detail : `Request failed (${res.status})`),
      env?.details,
      env?.request_id,
    );
  }

  if (!opts.schema) return data as z.infer<S>;
  const parsed = opts.schema.safeParse(data);
  if (!parsed.success) {
    throw new ApiError(res.status, "RESPONSE_SHAPE", "The server response did not match the expected schema.", parsed.error.issues);
  }
  return parsed.data;
}
