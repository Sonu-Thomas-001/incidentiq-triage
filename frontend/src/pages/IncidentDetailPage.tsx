import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { AuditTimeline } from "@/components/AuditTimeline";
import { CardSkeleton, ErrorState, errorMessage, PageHeader, PriorityChip, StatusChip, SyntheticBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Field, Select } from "@/components/ui/primitives";
import { DecisionPanel, type DecisionInput } from "@/components/triage/DecisionPanel";
import { GeminiPanel, MlPanel, PolicyPanel, RoutingPanel, uncertaintyWarnings } from "@/components/triage/AiPanels";
import { useTeams } from "@/hooks/useTeams";
import { ANALYST_ADMIN, STAFF, useAuth } from "@/lib/auth";
import { api } from "@/lib/endpoints";
import type { IncidentDetail, WorkflowRun } from "@/lib/schemas";
import { formatDate } from "@/lib/utils";

const LEVELS = [
  { v: "", label: "Not provided" },
  { v: "1", label: "1 – High" },
  { v: "2", label: "2 – Medium" },
  { v: "3", label: "3 – Low" },
];

function latestRun(runs?: WorkflowRun[]): WorkflowRun | null {
  const triage = (runs ?? []).filter((r) => r.kind === "triage");
  return triage.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0] ?? null;
}

export default function IncidentDetailPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const { hasRole } = useAuth();
  const { teams, teamName } = useTeams();
  const qc = useQueryClient();
  const isAnalyst = hasRole(...ANALYST_ADMIN);
  const isStaff = hasRole(...STAFF);

  const [impact, setImpact] = useState(params.get("impact") ?? "");
  const [urgency, setUrgency] = useState(params.get("urgency") ?? "");
  const [useGemini, setUseGemini] = useState(false);
  const [consent, setConsent] = useState(false);
  const [fresh, setFresh] = useState<WorkflowRun | null>(null);

  const incident = useQuery({ queryKey: ["incident", id], queryFn: () => api.getIncident(id) });
  const runs = useQuery({ queryKey: ["runs", id], queryFn: () => api.workflowRuns(id), enabled: isStaff });
  const config = useQuery({ queryKey: ["workflow-config"], queryFn: api.workflowConfig, enabled: isAnalyst });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["incident", id] });
    qc.invalidateQueries({ queryKey: ["runs", id] });
    qc.invalidateQueries({ queryKey: ["audit", id] });
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
    qc.invalidateQueries({ queryKey: ["queue"] });
  };

  const run = useMutation({
    mutationFn: (inc: IncidentDetail) =>
      api.runWorkflow(id, {
        expected_version: inc.version,
        impact: impact ? Number(impact) : undefined,
        urgency: urgency ? Number(urgency) : undefined,
        use_gemini: useGemini,
        external_data_consent: useGemini && consent,
      }),
    onSuccess: (r) => {
      setFresh(r);
      toast.success(r.reused ? "Existing triage result reused" : "Triage complete — awaiting analyst review");
      refresh();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      refresh();
    },
  });

  const decide = useMutation({
    mutationFn: async ({ inc, d, runId }: { inc: IncidentDetail; d: DecisionInput; runId?: string }) => {
      const reassign = inc.status !== "NEEDS_REVIEW";
      if (reassign) {
        return api.override(id, { expected_version: inc.version, team_id: d.team_id, priority: d.priority, reason: d.reason ?? "" });
      }
      return api.approveWorkflow(id, {
        expected_version: inc.version,
        team_id: d.team_id,
        priority: d.priority,
        reason: d.reason,
        run_id: runId,
      });
    },
    onSuccess: () => {
      toast.success("Decision recorded");
      refresh();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      refresh();
    },
  });

  if (incident.isPending) return <CardSkeleton rows={5} />;
  if (incident.isError) return <ErrorState error={incident.error} onRetry={() => incident.refetch()} />;
  const inc = incident.data;

  const currentRun = fresh ?? latestRun(runs.data);
  const ml = (currentRun?.ml as Record<string, unknown> | null | undefined) ?? null;
  const review = (currentRun?.review as Record<string, unknown> | null | undefined) ?? null;
  const routing = (currentRun?.routing as Record<string, unknown> | null | undefined) ?? null;
  const recommendedTeam = (review?.recommended_team_id as string | null | undefined) ?? inc.latest_prediction?.predicted_team_id ?? null;
  const recommendedPriority = (review?.recommended_priority as string | null | undefined) ?? inc.latest_prediction?.predicted_priority ?? null;
  const warnings = currentRun ? uncertaintyWarnings(ml, routing, (currentRun.input_issues as unknown[]) ?? []) : [];
  const geminiOn = (config.data?.gemini as { enabled?: boolean } | undefined)?.enabled === true;

  return (
    <>
      <PageHeader
        title="AI Triage Workspace"
        subtitle={`Incident ${inc.id.slice(0, 8)} · version ${inc.version}`}
        actions={
          <Button variant="outline" asChild>
            <Link to={`/incidents/${inc.id}/audit`}>Full audit timeline</Link>
          </Button>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Original incident (immutable)</CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <StatusChip status={inc.status} />
                {inc.is_synthetic && <SyntheticBadge />}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <h2 className="text-lg font-semibold text-slate-900">{inc.title}</h2>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{inc.description}</p>
              <dl className="grid grid-cols-2 gap-3 text-xs text-slate-600 sm:grid-cols-4">
                <div><dt className="text-slate-400">Approved category</dt><dd>{inc.approved_category ?? "—"}</dd></div>
                <div><dt className="text-slate-400">Approved priority</dt><dd><PriorityChip priority={inc.approved_priority} /></dd></div>
                <div><dt className="text-slate-400">Assigned team</dt><dd>{teamName(inc.current_assignment?.team_id)}</dd></div>
                <div><dt className="text-slate-400">Created</dt><dd>{formatDate(inc.created_at)}</dd></div>
              </dl>
              {inc.current_assignment?.reason && (
                <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {inc.current_assignment.is_override ? "Override reason" : "Approval note"}: {inc.current_assignment.reason}
                </p>
              )}
            </CardContent>
          </Card>

          {isAnalyst && (
            <Card>
              <CardHeader>
                <CardTitle>Run triage</CardTitle>
                <Badge tone="slate">Recommendation only</Badge>
              </CardHeader>
              <CardContent>
                <form className="space-y-3" onSubmit={(e) => e.preventDefault()} aria-label="Run triage form">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Impact" htmlFor="impact">
                      <Select id="impact" value={impact} onChange={(e) => setImpact(e.target.value)}>
                        {LEVELS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
                      </Select>
                    </Field>
                    <Field label="Urgency" htmlFor="urgency">
                      <Select id="urgency" value={urgency} onChange={(e) => setUrgency(e.target.value)}>
                        {LEVELS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
                      </Select>
                    </Field>
                  </div>
                  {geminiOn ? (
                    <div className="space-y-1 text-sm">
                      <label className="flex items-center gap-2">
                        <input type="checkbox" checked={useGemini} onChange={(e) => setUseGemini(e.target.checked)} /> Add optional Gemini summary
                      </label>
                      {useGemini && !inc.is_synthetic && (
                        <label className="flex items-center gap-2 text-xs text-amber-800">
                          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I authorize sending redacted text of this
                          non-synthetic incident to an external API.
                        </label>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Gemini assistance is disabled on the server.</p>
                  )}
                  <Button
                    onClick={() => run.mutate(inc)}
                    disabled={run.isPending || !["NEW", "TRIAGE_PENDING", "NEEDS_REVIEW"].includes(inc.status)}
                  >
                    <Play className="h-4 w-4" aria-hidden /> {run.isPending ? "Running…" : "Run triage / request review"}
                  </Button>
                  <p className="text-xs text-slate-500">
                    Running triage moves the incident to NEEDS_REVIEW for an analyst. It never writes to ServiceNow.
                  </p>
                </form>
              </CardContent>
            </Card>
          )}

          {currentRun && (
            <>
              {warnings.length > 0 && (
                <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                  <p className="font-medium">Uncertainty warnings</p>
                  <ul className="mt-1 list-disc pl-5 text-xs">
                    {warnings.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                </div>
              )}
              <div className="grid gap-6 lg:grid-cols-2">
                <MlPanel ml={ml} />
                <PolicyPanel ml={ml} priorityInputs={currentRun.priority_inputs as Record<string, unknown> | null} />
              </div>
              <GeminiPanel assist={(currentRun.assist as Record<string, unknown> | null | undefined) ?? null} />
              <RoutingPanel routing={routing} />
            </>
          )}
        </div>

        <div className="space-y-6">
          <DecisionPanel
            key={`${recommendedTeam}-${recommendedPriority}-${inc.status}`}
            status={inc.status}
            teams={teams}
            canDecide={isAnalyst}
            recommendedTeamId={recommendedTeam}
            recommendedPriority={recommendedPriority}
            currentTeamId={inc.current_assignment?.team_id}
            busy={decide.isPending}
            onSubmit={async (d) => {
              await decide.mutateAsync({ inc, d, runId: currentRun?.run_id }).catch(() => undefined);
            }}
          />
          <AuditTimeline incidentId={id} />
        </div>
      </div>
    </>
  );
}
