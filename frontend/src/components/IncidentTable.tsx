import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { EmptyState, PriorityChip, StatusChip, SyntheticBadge } from "@/components/common";
import { useTeams } from "@/hooks/useTeams";
import type { Incident } from "@/lib/schemas";
import { formatDate } from "@/lib/utils";

export function IncidentTable({
  items,
  teamByIncident,
  actions,
  emptyHint,
}: {
  items: Incident[];
  teamByIncident?: Record<string, string>;
  actions?: (i: Incident) => ReactNode;
  emptyHint?: string;
}) {
  const { teamName } = useTeams();
  if (items.length === 0) return <EmptyState title="No incidents match" hint={emptyHint} />;
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">Incidents</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-4 py-3">Incident</th>
            <th scope="col" className="px-4 py-3">Status</th>
            <th scope="col" className="px-4 py-3">Category</th>
            <th scope="col" className="px-4 py-3">Priority</th>
            <th scope="col" className="px-4 py-3">Source</th>
            {teamByIncident && <th scope="col" className="px-4 py-3">Team</th>}
            <th scope="col" className="px-4 py-3">Created</th>
            {actions && <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {items.map((i) => (
            <tr key={i.id} className="hover:bg-sky-50/40">
              <td className="max-w-xs px-4 py-3">
                <Link to={`/incidents/${i.id}`} className="font-medium text-slate-900 hover:text-sky-700">
                  {i.title}
                </Link>
                <p className="font-mono text-[11px] text-slate-400">{i.id.slice(0, 8)}</p>
              </td>
              <td className="px-4 py-3"><StatusChip status={i.status} /></td>
              <td className="px-4 py-3 text-slate-600">{i.approved_category ?? "—"}</td>
              <td className="px-4 py-3"><PriorityChip priority={i.approved_priority} /></td>
              <td className="px-4 py-3">{i.is_synthetic ? <SyntheticBadge /> : <span className="text-xs text-slate-500">Local</span>}</td>
              {teamByIncident && <td className="px-4 py-3 text-slate-600">{teamName(teamByIncident[i.id])}</td>}
              <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{formatDate(i.created_at)}</td>
              {actions && <td className="px-4 py-3 text-right">{actions(i)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
