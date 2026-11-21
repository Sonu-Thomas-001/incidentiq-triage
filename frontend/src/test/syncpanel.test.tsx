import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SyncPanel } from "@/components/servicenow/SyncPanel";
import { renderApp } from "./utils";

const preview = (over: Record<string, unknown> = {}) => ({
  sync_id: "s-1",
  target_instance_host: "mock.service-now.com",
  external_number: "INC9000001",
  external_sys_id: "abc",
  target_team: "Network Operations",
  mode: "mock",
  writes_allowed: true,
  field_changes: { assignment_group: { from: "old", to: "new" } },
  ...over,
});

const ID = "11111111-1111-1111-1111-111111111111";
const base = (p: Record<string, unknown>) => ({
  [`GET /integrations/servicenow/incidents/${ID}/sync`]: { body: [] },
  [`POST /integrations/servicenow/incidents/${ID}/sync/preview`]: { body: p },
});

describe("SyncPanel", () => {
  it("keeps approve disabled until confirmed and host typed", async () => {
    const user = userEvent.setup();
    renderApp(<SyncPanel incidentId={ID} number="INC9000001" hasAssignment />, { role: "TRIAGE_ANALYST", handlers: base(preview()) });
    await user.click(await screen.findByRole("button", { name: /preview sync/i }));
    const approve = await screen.findByRole("button", { name: /approve and update/i });
    expect(approve).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(approve).toBeDisabled();
    await user.type(screen.getByLabelText(/type the instance host/i), "mock.service-now.com");
    await waitFor(() => expect(approve).toBeEnabled());
  });

  it("warns and offers no approval when writes are disabled", async () => {
    const user = userEvent.setup();
    renderApp(<SyncPanel incidentId={ID} hasAssignment />, {
      role: "TRIAGE_ANALYST",
      handlers: base(preview({ mode: "read_only", writes_allowed: false })),
    });
    await user.click(await screen.findByRole("button", { name: /preview sync/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/writes are disabled/i);
    expect(screen.queryByRole("button", { name: /approve and update/i })).toBeNull();
  });

  it("disables preview without an approved assignment", async () => {
    renderApp(<SyncPanel incidentId={ID} hasAssignment={false} />, { role: "TRIAGE_ANALYST", handlers: base(preview()) });
    expect(await screen.findByRole("button", { name: /preview sync/i })).toBeDisabled();
  });
});
