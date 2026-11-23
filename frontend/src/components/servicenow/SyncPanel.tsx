import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ErrorState, errorMessage } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/endpoints";
import { formatDate } from "@/lib/utils";

type Rec = Record<string, unknown>;

const TONE: Record<string, "slate" | "sky" | "amber" | "green" | "rose"> = {
  PREVIEWED: "sky",
  IN_PROGRESS: "amber",
  SUCCEEDED: "green",
  FAILED: "rose",
};

function Change({ field, change }: { field: string; change: Rec }) {
  return (
    <li className="font-mono text-xs">
      {field}: <span className="text-rose-700">{String(change.from ?? "(empty)")}</span> →{" "}
      <span className="text-emerald-700">{String(change.to)}</span>
    </li>
  );
}

export function SyncPanel({ incidentId, number, hasAssignment }: { incidentId: string; number?: string | null; hasAssignment: boolean }) {
  const qc = useQueryClient();
  const [preview, setPreview] = useState<Rec | null>(null);
  const [typedHost, setTypedHost] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const history = useQuery({ queryKey: ["sn-sync", incidentId], queryFn: () => api.snSyncHistory(incidentId) });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["sn-sync", incidentId] });
    qc.invalidateQueries({ queryKey: ["audit", incidentId] });
  };

  const doPreview = useMutation({
    mutationFn: () => api.snSyncPreview(incidentId),
    onSuccess: (r) => {
      setPreview(r);
      setTypedHost("");
      setConfirmed(false);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const approve = useMutation({
    mutationFn: () =>
      api.snSyncApprove(incidentId, {
        preview_id: String(preview?.sync_id),
        confirm: confirmed,
        confirm_instance_host: typedHost.trim(),
      }),
    onSuccess: (r) => {
      toast.success((r.result as Rec | null)?.already_applied ? "ServiceNow already had this group" : "Assignment group updated in ServiceNow");
      setPreview(null);
      invalidate();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      invalidate();
    },
  });

  const host = String(preview?.target_instance_host ?? "");
  const changes = (preview?.field_changes as Record<string, Rec> | undefined) ?? {};
  const writesAllowed = preview?.writes_allowed === true;
  const canApprove = writesAllowed && confirmed && typedHost.trim().toLowerCase() === host.toLowerCase();

  return (
    <Card>
      <CardHeader>
        <CardTitle>ServiceNow sync</CardTitle>
        <Badge tone="slate">{number ?? "linked record"}</Badge>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          Writes only the approved assignment group, only after you preview and confirm. Nothing is sent during triage.
        </p>
        {!hasAssignment && <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">Approve an assignment before syncing.</p>}
        <Button variant="outline" disabled={!hasAssignment || doPreview.isPending} onClick={() => doPreview.mutate()}>
          <CloudUpload className="h-4 w-4" aria-hidden /> {doPreview.isPending ? "Reading ServiceNow…" : "Preview sync"}
        </Button>

        {preview && (
          <div className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/60 p-3" aria-label="Sync preview">
            <dl className="grid grid-cols-[110px_1fr] gap-y-1 text-xs">
              <dt className="text-slate-500">Instance</dt><dd className="font-mono">{host}</dd>
              <dt className="text-slate-500">Incident</dt><dd className="font-mono">{String(preview.external_number ?? "—")}</dd>
              <dt className="text-slate-500">sys_id</dt><dd className="break-all font-mono">{String(preview.external_sys_id)}</dd>
              <dt className="text-slate-500">Target team</dt><dd>{String(preview.target_team ?? "—")}</dd>
              <dt className="text-slate-500">Mode</dt><dd>{String(preview.mode)}</dd>
            </dl>
            <div>
              <p className="text-xs font-medium text-slate-700">Exact fields to be changed</p>
              <ul className="mt-1 space-y-1">{Object.entries(changes).map(([f, c]) => <Change key={f} field={f} change={c} />)}</ul>
            </div>
            {!writesAllowed ? (
              <p role="alert" className="flex items-start gap-2 rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-900">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> Writes are disabled in “{String(preview.mode)}” mode. Switch the server to <code>SERVICENOW_MODE=live</code> to apply.
              </p>
            ) : (
              <div className="space-y-2">
                <label className="flex items-start gap-2 text-xs">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  I approve changing the fields above on this ServiceNow record.
                </label>
                <Input aria-label="Type the instance host to confirm" placeholder={`Type ${host} to confirm`} value={typedHost} onChange={(e) => setTypedHost(e.target.value)} />
                <Button disabled={!canApprove || approve.isPending} onClick={() => approve.mutate()}>
                  {approve.isPending ? "Updating…" : "Approve and update ServiceNow"}
                </Button>
              </div>
            )}
          </div>
        )}

        <div>
          <p className="text-xs font-medium text-slate-700">Sync history</p>
          {history.isError ? <ErrorState error={history.error} /> : (history.data ?? []).length === 0 ? (
            <p className="text-xs text-slate-500">No sync attempts yet.</p>
          ) : (
            <ul className="mt-1 space-y-1">
              {(history.data ?? []).map((r) => (
                <li key={String(r.sync_id)} className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={TONE[String(r.status)] ?? "slate"}>{String(r.status)}</Badge>
                  <span className="text-slate-500">{formatDate(String(r.created_at))}</span>
                  {r.last_error ? <span className="text-rose-700">{String(r.last_error)}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
