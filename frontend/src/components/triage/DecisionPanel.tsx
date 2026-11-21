import { useState } from "react";
import { Gavel } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Field, Select, Textarea } from "@/components/ui/primitives";
import { PRIORITIES, type Status, type Team } from "@/lib/schemas";

export interface DecisionInput {
  team_id: string;
  priority?: string;
  reason?: string;
  isDeviation: boolean;
}

export function DecisionPanel({
  status,
  teams,
  canDecide,
  recommendedTeamId,
  recommendedPriority,
  currentTeamId,
  busy,
  onSubmit,
}: {
  status: Status;
  teams: Team[];
  canDecide: boolean;
  recommendedTeamId?: string | null;
  recommendedPriority?: string | null;
  currentTeamId?: string | null;
  busy?: boolean;
  onSubmit: (d: DecisionInput) => void | Promise<void>;
}) {
  const reassigning = status === "ASSIGNED" || status === "ACCEPTED" || status === "REASSIGNED";
  const reviewing = status === "NEEDS_REVIEW";
  // When reassigning, start empty so the analyst picks a new team instead of silently re-selecting the ML recommendation.
  const [teamId, setTeamId] = useState(reassigning ? "" : (recommendedTeamId ?? ""));
  const [priority, setPriority] = useState(recommendedPriority ?? "");
  const [reason, setReason] = useState("");

  const deviates =
    reassigning ||
    !recommendedTeamId ||
    teamId !== recommendedTeamId ||
    (!!recommendedPriority && priority !== recommendedPriority);
  const reasonRequired = deviates;
  const reasonOk = !reasonRequired || reason.trim().length >= 5;
  const valid = !!teamId && reasonOk;

  if (!canDecide) {
    return (
      <Card>
        <CardContent className="text-sm text-slate-600">
          Your role cannot approve or override assignments. Ask a triage analyst or administrator.
        </CardContent>
      </Card>
    );
  }
  if (!reviewing && !reassigning) {
    return (
      <Card>
        <CardContent className="text-sm text-slate-600">
          Run the triage workflow first. The incident then moves to NEEDS_REVIEW and a decision can be made here.
        </CardContent>
      </Card>
    );
  }

  const label = reassigning ? "Override / reassign" : deviates ? "Approve with override" : "Approve recommendation";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gavel className="h-4 w-4 text-sky-600" aria-hidden /> Analyst decision
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={(e) => e.preventDefault()} aria-label="Decision form">
          <Field label={reassigning ? "Reassign to team" : "Assign to team"} htmlFor="decision-team">
            <Select id="decision-team" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
              <option value="">Select a team…</option>
              {teams
                .filter((t) => !(reassigning && t.id === currentTeamId))
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.id === recommendedTeamId ? " (recommended)" : ""}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Approved priority" htmlFor="decision-priority">
            <Select id="decision-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="">Leave unset</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                  {p === recommendedPriority ? " (policy)" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={reasonRequired ? "Reason (required)" : "Reason (optional)"}
            htmlFor="decision-reason"
            error={reasonRequired && reason.length > 0 && !reasonOk ? "Enter at least 5 characters." : undefined}
            hint={
              reasonRequired
                ? reassigning
                  ? "Required to reassign an incident that already has an assignment."
                  : "Required because this differs from the recommendation."
                : undefined
            }
          >
            <Textarea id="decision-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <ConfirmDialog
            trigger={
              <Button disabled={!valid || busy} className="w-full">
                {label}
              </Button>
            }
            title={`${label}?`}
            description="This records an approved human decision and an audit event. Nothing is written to ServiceNow."
            confirmLabel="Confirm"
            onConfirm={() =>
              onSubmit({ team_id: teamId, priority: priority || undefined, reason: reason.trim() || undefined, isDeviation: deviates })
            }
          >
            <p className="text-sm text-slate-700">
              Team: <strong>{teams.find((t) => t.id === teamId)?.name ?? "—"}</strong> · Priority:{" "}
              <strong>{priority || "unset"}</strong>
            </p>
          </ConfirmDialog>
        </form>
      </CardContent>
    </Card>
  );
}
