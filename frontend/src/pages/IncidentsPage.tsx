import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { CardSkeleton, ErrorState, PageHeader } from "@/components/common";
import { IncidentTable } from "@/components/IncidentTable";
import { Pagination } from "@/components/Pagination";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/primitives";
import { useTeams } from "@/hooks/useTeams";
import { api } from "@/lib/endpoints";
import { PRIORITIES, STATUSES } from "@/lib/schemas";

const PAGE_SIZE = 15;

export default function IncidentsPage() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [teamId, setTeamId] = useState("");
  const { teams } = useTeams();

  const filters = { page, page_size: PAGE_SIZE, q: q.trim() || undefined, status: status || undefined, priority: priority || undefined, team_id: teamId || undefined };
  const query = useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => api.listIncidents(filters),
    placeholderData: keepPreviousData,
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Incident Explorer"
        subtitle="Search and filter incidents you are allowed to see."
        actions={
          <Button asChild>
            <Link to="/incidents/new">New incident</Link>
          </Button>
        }
      />
      <form role="search" className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => e.preventDefault()}>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" aria-hidden />
          <Input aria-label="Search title" placeholder="Search title…" className="pl-9" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        </div>
        <Select aria-label="Filter by status" value={status} onChange={(e) => reset(setStatus)(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
        <Select aria-label="Filter by priority" value={priority} onChange={(e) => reset(setPriority)(e.target.value)}>
          <option value="">All priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </Select>
        <Select aria-label="Filter by team" value={teamId} onChange={(e) => reset(setTeamId)(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </Select>
      </form>
      {query.isPending ? (
        <CardSkeleton rows={6} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : (
        <>
          <IncidentTable items={query.data.items} emptyHint="Try clearing filters, or create a new incident." />
          <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
