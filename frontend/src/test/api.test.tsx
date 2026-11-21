import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, request, session } from "@/lib/api";
import { z } from "zod";
import { mockFetch } from "./utils";

describe("api client", () => {
  it("maps the structured error envelope to ApiError", async () => {
    mockFetch({ "GET /x": { status: 409, body: { error: { code: "STALE_VERSION", message: "stale", request_id: "r1" } } } });
    const err = (await request("/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("STALE_VERSION");
    expect(err.isStale).toBe(true);
    expect(err.requestId).toBe("r1");
  });

  it("clears the session and notifies on 401", async () => {
    session.set("tok");
    const listener = vi.fn();
    const off = session.onUnauthorized(listener);
    mockFetch({ "GET /me": { status: 401, body: { error: { code: "UNAUTHORIZED", message: "no" } } } });
    await request("/me").catch(() => undefined);
    off();
    expect(session.token).toBeNull();
    expect(listener).toHaveBeenCalledOnce();
  });

  it("sends the bearer token and never on login", async () => {
    session.set("tok");
    const { fn } = mockFetch({ "GET /a": { body: {} }, "POST /auth/login": { body: {} } });
    await request("/a");
    await request("/auth/login", { method: "POST", body: {}, auth: false });
    expect((fn.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok" });
    expect((fn.mock.calls[1][1] as RequestInit).headers).not.toHaveProperty("Authorization");
  });

  it("rejects responses that do not match the schema", async () => {
    mockFetch({ "GET /s": { body: { nope: 1 } } });
    const err = (await request("/s", { schema: z.object({ id: z.string() }) }).catch((e) => e)) as ApiError;
    expect(err.code).toBe("RESPONSE_SHAPE");
  });

  it("reports network failures clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fail")));
    const err = (await request("/z").catch((e) => e)) as ApiError;
    expect(err.code).toBe("NETWORK_ERROR");
  });
});

describe("login", () => {
  it("shows validation and backend errors", async () => {
    const { default: LoginPage } = await import("@/pages/LoginPage");
    const { renderApp } = await import("./utils");
    renderApp(<LoginPage />, {
      handlers: { "POST /auth/login": { status: 401, body: { error: { code: "INVALID_CREDENTIALS", message: "Invalid email or password" } } } },
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Email is required")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "a@synthetic.example");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Invalid email or password"));
    expect(session.token).toBeNull();
  });
});
