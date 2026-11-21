import { useQuery } from "@tanstack/react-query";
import { CardSkeleton, EmptyState, ErrorState } from "@/components/common";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/endpoints";
import { formatDate } from "@/lib/utils";

const TONE: Record<string, "sky" | "teal" | "violet" | "amber" | "green" | "slate" | "rose"> = {
  INCIDENT_CREATED: "sky",
  TRIAGE_REQUESTED: "sky",
  PREDICTION_RECORDED: "violet",
  TRIAGE_PREDICTION_RECORDED: "violet",
  INCIDENT_ASSIGNED: "teal",
  ASSIGNMENT_OVERRIDDEN: "amber",
  INCIDENT_ACCEPTED: "green",
};

function tone(type: string) {
  if (type.includes("SERVICENOW") || type.includes("SYNC")) return "rose";
  return TONE[type] ?? "slate";
}

export function AuditTimeline({ incidentId }: { incidentId: string }) {
  const q = useQuery({ queryKey: ["audit", incidentId], queryFn: () => api.audit(incidentId) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit timeline</CardTitle>
      </CardHeader>
      <CardContent>
        {q.isPending ? (
          <CardSkeleton rows={3} />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <EmptyState title="No audit events yet" />
        ) : (
          <ol className="relative space-y-4 border-l border-slate-200 pl-5" aria-label="Audit events">
            {q.data.items.map((e) => {
              const reason = e.details && typeof e.details.reason === "string" ? e.details.reason : null;
              return (
                <li key={e.id} className="relative">
                  <span className="absolute -left-[26px] top-1 h-3 w-3 rounded-full border-2 border-white bg-sky-300 shadow" aria-hidden />
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={tone(e.event_type)}>{e.event_type.replace(/_/g, " ")}</Badge>
                    {e.from_status && e.to_status && (
                      <span className="text-xs text-slate-500">
                        {e.from_status} → {e.to_status}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{formatDate(e.created_at)}</p>
                  {reason && <p className="mt-1 text-sm text-slate-700">Reason: {reason}</p>}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
