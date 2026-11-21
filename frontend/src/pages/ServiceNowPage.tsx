import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CardSkeleton, EmptyState, ErrorState, errorMessage, PageHeader } from "@/components/common";
import { Pagination } from "@/components/Pagination";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input, Select } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/endpoints";

const STATES = [
  { v: "", label: "Any state" },
  { v: "1", label: "New" },
  { v: "2", label: "In Progress" },
  { v: "3", label: "On Hold" },
];

export default function ServiceNowPage() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [imported, setImported] = useState<Record<string, string>>({});

  const health = useQuery({ queryKey: ["sn-health"], queryFn: api.snHealth, retry: false });
  const disabled = (health.error instanceof ApiError && health.error.code === "INTEGRATION_DISABLED") || health.data?.enabled === false;
  const ready = health.data?.enabled === true && health.data?.reachable === true;

  const incidents = useQuery({
    queryKey: ["sn-incidents", page, state, q],
    queryFn: () => api.snIncidents({ page, page_size: 10, state: state || undefined, q: q || undefined }),
    enabled: ready,
    retry: false,
  });
  const groups = useQuery({ queryKey: ["sn-groups"], queryFn: () => api.snGroups(1), enabled: ready, retry: false });

  const doImport = useMutation({
    mutationFn: (sys_id: string) => api.snImport(sys_id),
    onSuccess: (r, sys_id) => {
      setImported((m) => ({ ...m, [sys_id]: String(r.incident_id) }));
      toast.success(r.created ? "Imported as a local NEW incident" : "Already imported");
      qc.invalidateQueries({ queryKey: ["incidents"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const h = health.data ?? {};

  return (
    <>
      <PageHeader title="ServiceNow" subtitle="Read-only view of your developer instance. Import never writes back; sync needs a preview and explicit approval." />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          {health.data && <Badge tone={disabled ? "slate" : ready ? "green" : "rose"}>{disabled ? "disabled" : ready ? "reachable" : "unreachable"}</Badge>}
        </CardHeader>
        <CardContent className="text-sm">
          {health.isPending ? <CardSkeleton rows={1} /> : health.isError ? <ErrorState error={health.error} onRetry={() => health.refetch()} /> : disabled ? (
            <p className="text-slate-600">
              Disabled on the server (<code>SERVICENOW_ENABLED=false</code>). Set it to <code>true</code> in <code>backend/.env</code> with <code>SERVICENOW_MODE=mock</code> for a safe local demo, or
              configure your developer instance and use <code>read_only</code>. See docs/servicenow-integration.md.
            </p>
          ) : (
            <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-slate-400">Mode</dt><dd>{String(h.mode)}</dd></div>
              <div><dt className="text-slate-400">Instance</dt><dd className="font-mono">{String(h.instance_host ?? "—")}</dd></div>
              <div><dt className="text-slate-400">Credentials</dt><dd>{h.credentials_configured ? "configured" : "not configured"}</dd></div>
              <div><dt className="text-slate-400">Writes allowed</dt><dd>{h.writes_allowed ? "yes (after approval)" : "no"}</dd></div>
              {h.detail ? <div className="sm:col-span-2 lg:col-span-4 text-rose-700">{String(h.detail)}</div> : null}
            </dl>
          )}
        </CardContent>
      </Card>

      {ready && (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <Card>
            <CardHeader><CardTitle>Remote incidents</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Input aria-label="Search remote incidents" className="max-w-xs" placeholder="Search short description" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
                <Select aria-label="Remote state" className="w-40" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
                  {STATES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                </Select>
              </div>
              {incidents.isPending ? <CardSkeleton rows={4} /> : incidents.isError ? <ErrorState error={incidents.error} onRetry={() => incidents.refetch()} /> : incidents.data.items.length === 0 ? (
                <EmptyState title="No remote incidents match" hint="Change the filters or create a record in your ServiceNow instance." />
              ) : (
                <>
                  <div className="overflow-x-auto rounded-2xl border border-blue-100">
                    <table className="w-full text-left text-sm">
                      <thead className="text-xs uppercase tracking-wide">
                        <tr><th className="px-3 py-2">Number</th><th className="px-3 py-2">Short description</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Impact / urgency</th><th className="px-3 py-2" /></tr>
                      </thead>
                      <tbody>
                        {incidents.data.items.map((r) => {
                          const sys = String(r.sys_id);
                          const local = imported[sys];
                          return (
                            <tr key={sys} className="border-t border-blue-50">
                              <td className="px-3 py-2 font-mono text-xs">{String(r.number ?? "—")}</td>
                              <td className="max-w-md px-3 py-2">{String(r.title)}</td>
                              <td className="px-3 py-2"><Badge tone={r.importable ? "sky" : "slate"}>{String(r.state_label)}</Badge></td>
                              <td className="px-3 py-2 text-xs">{String(r.impact ?? "—")} / {String(r.urgency ?? "—")}</td>
                              <td className="px-3 py-2 text-right">
                                {local ? (
                                  <Button size="sm" variant="outline" asChild><Link to={`/incidents/${local}`}>Open</Link></Button>
                                ) : (
                                  <Button size="sm" disabled={!r.importable || doImport.isPending} onClick={() => doImport.mutate(sys)} aria-label={`Import ${String(r.number)}`}>
                                    <Download className="h-3.5 w-3.5" aria-hidden /> Import
                                  </Button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <Pagination page={page} pageSize={incidents.data.page_size} total={incidents.data.total ?? incidents.data.items.length} onPage={setPage} />
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Assignment groups</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-xs">
              <p className="text-slate-500">Copy a sys_id into Admin Settings to map it to a local team.</p>
              {groups.isPending ? <CardSkeleton rows={2} /> : groups.isError ? <ErrorState error={groups.error} /> : (
                <ul className="space-y-2">
                  {groups.data.items.map((g) => (
                    <li key={String(g.sys_id)} className="rounded-xl bg-blue-50/60 px-3 py-2">
                      <p className="font-medium text-slate-800">{String(g.name)}</p>
                      <p className="break-all font-mono text-[11px] text-slate-500">{String(g.sys_id)}</p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
