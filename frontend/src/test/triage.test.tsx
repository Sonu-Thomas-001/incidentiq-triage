import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";
import { DecisionPanel } from "@/components/triage/DecisionPanel";
import { GeminiPanel, MlPanel, PolicyPanel, uncertaintyWarnings } from "@/components/triage/AiPanels";
import IncidentDetailPage from "@/pages/IncidentDetailPage";
import { incident, renderApp } from "./utils";

const teams = [
  { id: "t-net", name: "Network Operations" },
  { id: "t-app", name: "Application Support" },
];

const demoMl = {
  status: "DEMO",
  is_demo: true,
  outputs: {
    category: { available: true, label: "Network", confidence: 0.91, confidence_kind: "calibrated_probability", model_version: "cat-1", provenance: "real", explanation_method: "linear coefficients", explanation_features: [{ feature: "vpn", contribution: 1.2 }] },
    team: { available: true, label: "Network Operations", confidence: 0.55, confidence_kind: "calibrated_probability", model_version: "team-1", provenance: "synthetic-demo", explanation_features: [] },
    priority: { available: true, label: "P2", evidence: "impact=2, urgency=2" },
  },
  disclaimer: "Recommendation only.",
};

const run = (over = {}) => ({
  run_id: "r-1",
  kind: "triage",
  status: "COMPLETED",
  reused: false,
  outcome: "NEEDS_REVIEW",
  prediction_id: "p-1",
  input_issues: [],
  priority_inputs: { impact: { value: 2, source: "request" }, urgency: { value: 2, source: "request" } },
  ml: demoMl,
  explanation: {},
  assist: { status: "SKIPPED", source: "LLM", message: "Gemini assistance was not requested.", output: null },
  routing: { decision: "NEEDS_REVIEW", routing_enabled: false, reasons: ["routing_disabled"], checks: [{ task: "team", passed: false, threshold: 0.9, reason: "synthetic_model" }] },
  review: { required: true, recommended_team_id: "t-net", recommended_priority: "P2" },
  created_at: "2026-01-01T10:05:00Z",
  ...over,
});

describe("triage panels keep sources distinct", () => {
  it("labels demo ML output and never invents confidence", () => {
    renderApp(<MlPanel ml={{ ...demoMl, outputs: { ...demoMl.outputs, team: { available: true, label: "X" } } }} />, { role: "ADMIN" });
    expect(screen.getByText(/DEMO output/)).toBeInTheDocument();
    expect(screen.getByText("No calibrated confidence")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
  });

  it("shows NOT_READY without fabricating a prediction", () => {
    const ml = { status: "NOT_READY", is_demo: false, outputs: { category: { available: false, reason: "model missing" }, team: { available: false, reason: "model missing" } } };
    renderApp(<MlPanel ml={ml} />, { role: "ADMIN" });
    expect(screen.getByText(/No prediction was fabricated/)).toBeInTheDocument();
    expect(screen.getAllByText(/Unavailable/).length).toBe(2);
  });

  it("describes priority as a deterministic policy, separate from ML", () => {
    renderApp(<PolicyPanel ml={demoMl} priorityInputs={null} />, { role: "ADMIN" });
    expect(screen.getByText("Deterministic policy")).toBeInTheDocument();
    expect(screen.getByText(/not a learned model/i)).toBeInTheDocument();
  });

  it("labels the Gemini summary as LLM output", () => {
    renderApp(<GeminiPanel assist={{ status: "OK", output: { summary: "VPN drops", extracted: {}, missing_information: ["OS version"] } }} />, { role: "ADMIN" });
    expect(screen.getByText(/LLM · OK/)).toBeInTheDocument();
    expect(screen.getByText("OS version")).toBeInTheDocument();
    expect(screen.getByText(/never influences routing/i)).toBeInTheDocument();
  });

  it("derives uncertainty warnings", () => {
    const w = uncertaintyWarnings(demoMl, { routing_enabled: false }, []);
    expect(w).toEqual(expect.arrayContaining([expect.stringMatching(/synthetic/i), expect.stringMatching(/Low team confidence/), expect.stringMatching(/Routing is disabled/)]));
  });
});

describe("decision panel permissions and rules", () => {
  it("blocks roles that cannot decide", () => {
    renderApp(<DecisionPanel status="NEEDS_REVIEW" teams={teams as never} canDecide={false} onSubmit={() => undefined} />, { role: "REPORTER" });
    expect(screen.getByText(/cannot approve or override/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("approves the recommendation without a reason, through a confirmation dialog", async () => {
    const calls: unknown[] = [];
    renderApp(<DecisionPanel status="NEEDS_REVIEW" teams={teams as never} canDecide recommendedTeamId="t-net" recommendedPriority="P2" onSubmit={(d) => void calls.push(d)} />, { role: "ADMIN" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ team_id: "t-net", priority: "P2", isDeviation: false });
  });

  it("requires a reason when deviating from the recommendation", async () => {
    renderApp(<DecisionPanel status="NEEDS_REVIEW" teams={teams as never} canDecide recommendedTeamId="t-net" recommendedPriority="P2" onSubmit={() => undefined} />, { role: "ADMIN" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Assign to team"), "t-app");
    const btn = screen.getByRole("button", { name: "Approve with override" });
    expect(btn).toBeDisabled();
    await user.type(screen.getByLabelText(/Reason/), "Owned by apps team");
    expect(btn).toBeEnabled();
  });

  it("asks to run triage first for NEW incidents", () => {
    renderApp(<DecisionPanel status="NEW" teams={teams as never} canDecide onSubmit={() => undefined} />, { role: "ADMIN" });
    expect(screen.getByText(/run the triage workflow first/i)).toBeInTheDocument();
  });
});

function Page() {
  return (
    <Routes>
      <Route path="/incidents/:id" element={<IncidentDetailPage />} />
    </Routes>
  );
}

describe("triage workspace workflow", () => {
  const id = "11111111-1111-1111-1111-111111111111";

  it("runs triage with the current version and shows the demo result", async () => {
    let status = "NEW";
    const { calls } = renderApp(<Page />, {
      role: "TRIAGE_ANALYST",
      route: `/incidents/${id}?impact=2&urgency=2`,
      handlers: {
        [`GET /incidents/${id}`]: () => ({ body: incident({ status, version: status === "NEW" ? 1 : 3 }) }),
        [`GET /workflow/incidents/${id}/runs`]: () => ({ body: status === "NEW" ? [] : [run()] }),
        "GET /workflow/config": { body: { gemini: { enabled: false }, routing: { enabled: false, thresholds: {} } } },
        [`GET /incidents/${id}/audit`]: { body: { items: [], total: 0, page: 1, page_size: 100 } },
        [`POST /workflow/incidents/${id}/run`]: () => {
          status = "NEEDS_REVIEW";
          return { body: run() };
        },
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /run triage/i }));
    expect(await screen.findByText(/DEMO output/)).toBeInTheDocument();
    expect(screen.getByText("Uncertainty warnings")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ expected_version: 1, impact: 2, urgency: 2, use_gemini: false, external_data_consent: false });
  });

  it("reports a stale-version conflict without losing the page", async () => {
    renderApp(<Page />, {
      role: "TRIAGE_ANALYST",
      route: `/incidents/${id}`,
      handlers: {
        [`GET /incidents/${id}`]: { body: incident() },
        [`GET /workflow/incidents/${id}/runs`]: { body: [] },
        "GET /workflow/config": { body: { gemini: { enabled: false } } },
        [`GET /incidents/${id}/audit`]: { body: { items: [], total: 0, page: 1, page_size: 100 } },
        [`POST /workflow/incidents/${id}/run`]: { status: 409, body: { error: { code: "STALE_VERSION", message: "stale" } } },
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /run triage/i }));
    expect(await screen.findByText(/changed since you loaded/i)).toBeInTheDocument();
    expect(screen.getByText("Original incident (immutable)")).toBeInTheDocument();
  });

  it("hides run and decision controls from reporters", async () => {
    renderApp(<Page />, {
      role: "REPORTER",
      route: `/incidents/${id}`,
      handlers: {
        [`GET /incidents/${id}`]: { body: incident() },
        [`GET /incidents/${id}/audit`]: { body: { items: [], total: 0, page: 1, page_size: 100 } },
      },
    });
    expect(await screen.findByText("Original incident (immutable)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run triage/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cannot approve or override/i)).toBeInTheDocument();
  });
});
