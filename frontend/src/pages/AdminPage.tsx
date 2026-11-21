import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { CardSkeleton, ErrorState, errorMessage, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { useTeams } from "@/hooks/useTeams";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/endpoints";
import { ApiError } from "@/lib/api";

type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec => (v && typeof v === "object" ? (v as Rec) : {});

function MappingRow({ team, current, isAdmin }: { team: { id: string; name: string }; current: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const [val, setVal] = useState(current);
  const m = useMutation({
    mutationFn: () => api.snSetMapping(team.id, val.trim() || null),
    onSuccess: () => {
      toast.success("Mapping saved");
      qc.invalidateQueries({ queryKey: ["sn-mappings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const invalid = val.trim() !== "" && val.trim().length !== 32;
  return (
    <li className="grid items-center gap-2 sm:grid-cols-[180px_1fr_auto]">
      <span className="text-sm font-medium">{team.name}</span>
      <Input aria-label={`ServiceNow group sys_id for ${team.name}`} placeholder="32-character sys_id (optional)" value={val} disabled={!isAdmin} onChange={(e) => setVal(e.target.value)} />
      <Button size="sm" variant="outline" disabled={!isAdmin || invalid || m.isPending} onClick={() => m.mutate()}>Save</Button>
    </li>
  );
}

export default function AdminPage() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");
  const { teams } = useTeams();
  const config = useQuery({ queryKey: ["workflow-config"], queryFn: api.workflowConfig });
  const health = useQuery({ queryKey: ["sn-health"], queryFn: api.snHealth, retry: false });
  const mappings = useQuery({ queryKey: ["sn-mappings"], queryFn: api.snMappings, retry: false });
  const models = useQuery({ queryKey: ["model-metrics"], queryFn: api.modelMetrics });

  const routing = rec(config.data?.routing);
  const thresholds = rec(routing.thresholds);
  const gemini = rec(config.data?.gemini);
  const snDisabled = (health.error instanceof ApiError && health.error.code === "INTEGRATION_DISABLED") || health.data?.enabled === false;
  const h = rec(health.data);
  const mapped = new Map((mappings.data ?? []).map((m) => [String(m.team_id), String(m.servicenow_group_sys_id ?? "")]));

  return (
    <>
      <PageHeader title="Admin Settings" subtitle="Read-only view of server configuration. Secrets are never sent to the browser." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Routing thresholds</CardTitle><Badge tone={routing.enabled ? "green" : "amber"}>{routing.enabled ? "enabled" : "disabled"}</Badge></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {config.isPending ? <CardSkeleton rows={1} /> : config.isError ? <ErrorState error={config.error} /> : (
              <>
                <p>Category threshold: <strong>{String(thresholds.category ?? "—")}</strong></p>
                <p>Team threshold: <strong>{String(thresholds.team ?? "—")}</strong></p>
                <p className="text-xs text-slate-500">Configured via server environment. Routing is off by default and never auto-assigns.</p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Gemini assistance (optional)</CardTitle><Badge tone={gemini.enabled ? "green" : "slate"}>{gemini.enabled ? "enabled" : "disabled"}</Badge></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {config.isPending ? <CardSkeleton rows={1} /> : (
              <>
                <p>Credentials configured: <strong>{gemini.credentials_configured ? "yes" : "no"}</strong></p>
                <p>Model: <strong>{String(gemini.model ?? "—")}</strong></p>
                <p className="text-xs text-slate-500">LLM output is a drafting aid only and never affects routing.</p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>ServiceNow connection</CardTitle>
            <Badge tone={snDisabled ? "slate" : h.enabled ? "green" : "amber"}>{snDisabled ? "disabled" : h.enabled ? String(h.mode ?? "enabled") : "unknown"}</Badge>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {health.isPending ? <CardSkeleton rows={1} /> : snDisabled ? (
              <p className="text-slate-600">The integration is disabled on the server (SERVICENOW_ENABLED=false). The app works fully offline.</p>
            ) : health.isError ? <ErrorState error={health.error} /> : (
              Object.entries(h).filter(([, v]) => typeof v !== "object").map(([k, v]) => <p key={k}><span className="text-slate-500">{k}:</span> {String(v)}</p>)
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Model versions</CardTitle></CardHeader>
          <CardContent className="text-sm">
            {models.isPending ? <CardSkeleton rows={1} /> : models.isError ? <ErrorState error={models.error} /> : models.data.models.length === 0 ? (
              <p className="text-slate-600">{models.data.message}</p>
            ) : (
              <ul className="space-y-1">{models.data.models.map((m) => <li key={m.id} className="flex justify-between"><span>{m.name} <span className="font-mono text-xs text-slate-500">{m.version}</span></span><Badge>{m.status}</Badge></li>)}</ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>Team ↔ ServiceNow group mappings</CardTitle>{!isAdmin && <Badge tone="slate">read-only (admin edits)</Badge>}</CardHeader>
        <CardContent>
          {snDisabled ? <p className="text-sm text-slate-600">Enable the ServiceNow integration on the server to manage mappings.</p> : mappings.isError ? <ErrorState error={mappings.error} /> : (
            <ul className="space-y-3">
              {teams.map((t) => <MappingRow key={`${t.id}-${mapped.get(t.id) ?? ""}`} team={t} current={mapped.get(t.id) ?? ""} isAdmin={isAdmin} />)}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}
