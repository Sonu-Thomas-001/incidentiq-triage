import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { CardSkeleton, ErrorState, errorMessage, PageHeader } from "@/components/common";
import { IncidentTable } from "@/components/IncidentTable";
import { Pagination } from "@/components/Pagination";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Select, Textarea } from "@/components/ui/primitives";
import { useTeams } from "@/hooks/useTeams";
import { ANALYST_ADMIN, useAuth } from "@/lib/auth";
import { api } from "@/lib/endpoints";
import { STATUSES, type Incident } from "@/lib/schemas";

const PAGE_SIZE = 15;

function ReassignControl({ incident, teams, teamId, onDone }: { incident: Incident; teams: { id: string; name: string }[]; teamId: string; onDone: () => void }) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.override(incident.id, { expected_version: incident.version, team_id: target, reason: reason.trim() }),
    onSuccess: () => {
      toast.success("Incident reassigned");
      onDone();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      onDone();
    },
  });
  return (
    <ConfirmDialog
      trigger={<Button size="sm" variant="outline">Reassign</Button>}
      title="Reassign incident"
      description="Choose the new team and give a reason. This is recorded in the audit trail."
      confirmLabel="Reassign"
      onConfirm={async () => {
        if (!target || reason.trim().length < 5) {
          toast.error("Pick a team and enter a reason (at least 5 characters).");
          return;
        }
        await m.mutateAsync().catch(() => undefined);
      }}
    >
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor={`rt-${incident.id}`}>New team</label>
        <Select id={`rt-${incident.id}`} value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Select…</option>
          {teams.filter((t) => t.id !== teamId).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
        <label className="text-sm font-medium" htmlFor={`rr-${incident.id}`}>Reason</label>
        <Textarea id={`rr-${incident.id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
    </ConfirmDialog>
  );
}

export default function QueuesPage() {
  const { user, hasRole } = useAuth();
  const { teams, teamName } = useTeams();
  const qc = useQueryClient();
  const [selected, setSelected] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const teamId = selected || user?.team_id || teams[0]?.id || "";

  const query = useQuery({
    queryKey: ["queue", teamId, status, page],
    queryFn: () => api.queue(teamId, { page, page_size: PAGE_SIZE, status: status || undefined }),
    enabled: !!teamId,
    placeholderData: keepPreviousData,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["queue"] });
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const accept = useMutation({
    mutationFn: (i: Incident) => api.accept(i.id, i.version),
    onSuccess: () => {
      toast.success("Incident accepted");
      refresh();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      refresh();
    },
  });

  const canAccept = hasRole("SUPPORT_ENGINEER", "ADMIN");
  const canReassign = hasRole(...ANALYST_ADMIN);

  return (
    <>
      <PageHeader title="Team Queues" subtitle={`Incidents currently assigned to ${teamName(teamId)}.`} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Select aria-label="Team" value={teamId} onChange={(e) => { setSelected(e.target.value); setPage(1); }}>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
        <Select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      {!teamId || query.isPending ? (
        <CardSkeleton rows={5} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : (
        <>
          <IncidentTable
            items={query.data.items}
            teamByIncident={Object.fromEntries(query.data.items.map((i) => [i.id, teamId]))}
            emptyHint="Nothing is assigned to this team with these filters."
            actions={(i) => (
              <div className="flex justify-end gap-2">
                {canAccept && (i.status === "ASSIGNED" || i.status === "REASSIGNED") && (
                  <Button size="sm" onClick={() => accept.mutate(i)} disabled={accept.isPending}>Accept</Button>
                )}
                {canReassign && i.status !== "NEW" && i.status !== "TRIAGE_PENDING" && i.status !== "NEEDS_REVIEW" && (
                  <ReassignControl incident={i} teams={teams} teamId={teamId} onDone={refresh} />
                )}
              </div>
            )}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
