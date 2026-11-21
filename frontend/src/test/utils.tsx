import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { vi } from "vitest";
import { AuthProvider } from "@/lib/auth";
import { session } from "@/lib/api";
import type { Role } from "@/lib/schemas";

export type Handler = (req: { url: URL; method: string; body: unknown }) => { status?: number; body: unknown } | undefined;

// Stubs fetch for unit tests only; the application itself always talks to the real API.
export function mockFetch(handlers: Record<string, Handler | { status?: number; body: unknown }>) {
  const calls: { url: URL; method: string; body: unknown }[] = [];
  const fn = vi.fn(async (input: URL | string, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const key = `${method} ${url.pathname.replace(/^\/api\/v1/, "")}`;
    const h = handlers[key];
    const res = typeof h === "function" ? h({ url, method, body }) : h;
    if (!res) return new Response(JSON.stringify({ error: { code: "NOT_MOCKED", message: key } }), { status: 500 });
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200 });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

export const userFor = (role: Role, team_id: string | null = null) => ({
  id: "u-1",
  email: `${role.toLowerCase()}@synthetic.example`,
  full_name: `Demo ${role}`,
  role,
  team_id,
  is_synthetic: true,
});

export function renderApp(ui: ReactElement, opts: { role?: Role; route?: string; handlers?: Record<string, Handler | { status?: number; body: unknown }> } = {}) {
  if (opts.role) session.set("test-token");
  const m = mockFetch({
    "GET /auth/me": { body: userFor(opts.role ?? "ADMIN") },
    "GET /teams": { body: [{ id: "t-net", name: "Network Operations" }, { id: "t-app", name: "Application Support" }] },
    ...opts.handlers,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[opts.route ?? "/"]}>
        <AuthProvider>
          {ui}
          <Toaster />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, ...m };
}

export const incident = (over: Record<string, unknown> = {}) => ({
  id: "11111111-1111-1111-1111-111111111111",
  title: "VPN keeps dropping",
  description: "The VPN disconnects every few minutes.",
  reporter_id: "u-1",
  status: "NEW",
  approved_priority: null,
  approved_category: null,
  is_synthetic: true,
  version: 1,
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
  current_assignment: null,
  latest_prediction: null,
  ...over,
});
