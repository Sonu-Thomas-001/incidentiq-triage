import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { IncidentTable } from "@/components/IncidentTable";
import AppShellHarness from "./shellHarness";
import CreateIncidentPage, { composeDescription, incidentFormSchema } from "@/pages/CreateIncidentPage";
import IncidentsPage from "@/pages/IncidentsPage";
import { incident, renderApp } from "./utils";

describe("create incident form", () => {
  it("validates required fields before calling the API", async () => {
    const { calls } = renderApp(<CreateIncidentPage />, { role: "REPORTER" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /create incident/i }));
    expect(await screen.findByText(/at least 5 characters/i)).toBeInTheDocument();
    expect(screen.getByText(/at least 10 characters/i)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("posts title and composed description, then offers triage", async () => {
    const created = incident({ id: "22222222-2222-2222-2222-222222222222" });
    const { calls } = renderApp(<CreateIncidentPage />, {
      role: "REPORTER",
      handlers: { "POST /incidents": { status: 201, body: created } },
    });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Short description"), "VPN keeps dropping");
    await user.type(screen.getByLabelText("Detailed description"), "Disconnects every few minutes today");
    await user.type(screen.getByLabelText(/^Service/), "VPN");
    await user.click(screen.getByRole("button", { name: /create incident/i }));
    const link = await screen.findByRole("link", { name: /open triage workspace/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/incidents/22222222"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ title: "VPN keeps dropping", description: "Disconnects every few minutes today\n\n---\nService: VPN" });
  });

  it("composeDescription leaves text unchanged without metadata", () => {
    const v = incidentFormSchema.parse({ title: "Printer jam", description: "Paper jam on floor 2", impact: 2, urgency: 2 });
    expect(composeDescription(v)).toBe("Paper jam on floor 2");
  });
});

describe("incident table", () => {
  it("renders status, priority and synthetic labels", () => {
    renderApp(
      <IncidentTable items={[incident({ status: "ASSIGNED", approved_priority: "P2" }) as never]} />,
      { role: "ADMIN" },
    );
    const row = screen.getByRole("row", { name: /VPN keeps dropping/ });
    expect(within(row).getByText("ASSIGNED")).toBeInTheDocument();
    expect(within(row).getByText("P2")).toBeInTheDocument();
    expect(within(row).getByText(/synthetic demo/i)).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    renderApp(<IncidentTable items={[]} />, { role: "ADMIN" });
    expect(screen.getByText(/no incidents match/i)).toBeInTheDocument();
  });
});

describe("incident explorer", () => {
  it("passes filters and pagination to the API", async () => {
    const page = { items: [incident()], total: 40, page: 1, page_size: 15 };
    const { calls } = renderApp(<IncidentsPage />, { role: "ADMIN", handlers: { "GET /incidents": { body: page } } });
    await screen.findByText("VPN keeps dropping");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter by status"), "NEEDS_REVIEW");
    await waitFor(() => expect(calls.some((c) => c.url.searchParams.get("status") === "NEEDS_REVIEW")).toBe(true));
    await user.click(screen.getByRole("button", { name: /next page/i }));
    await waitFor(() => expect(calls.some((c) => c.url.searchParams.get("page") === "2")).toBe(true));
  });

  it("surfaces API errors with retry", async () => {
    renderApp(<IncidentsPage />, {
      role: "ADMIN",
      handlers: { "GET /incidents": { status: 500, body: { error: { code: "INTERNAL", message: "boom" } } } },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

describe("role-based navigation", () => {
  it("hides staff pages from reporters", async () => {
    renderApp(<AppShellHarness />, { role: "REPORTER" });
    expect(await screen.findByRole("link", { name: /incident explorer/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /admin settings/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /team queues/i })).not.toBeInTheDocument();
  });

  it("shows all pages to admins", async () => {
    renderApp(<AppShellHarness />, { role: "ADMIN" });
    for (const name of [/overview/i, /team queues/i, /analytics/i, /admin settings/i]) {
      expect(await screen.findByRole("link", { name })).toBeInTheDocument();
    }
  });
});
