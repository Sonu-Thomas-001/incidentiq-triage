import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CardSkeleton, ErrorState, PageHeader, UnavailableNote } from "@/components/common";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/endpoints";
import { pct } from "@/lib/utils";

export const PALETTE = ["#123a99", "#1d5fd8", "#4aa3f5", "#8cc9fb", "#2dd4bf", "#a5b4fc", "#bfe1fc", "#fde68a"];

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card className="overflow-hidden border-t-4 border-t-blue-500 bg-gradient-to-br from-white to-blue-50">
      <CardContent className="space-y-1 pt-5">
        <p className="text-xs font-medium uppercase tracking-wide text-blue-700/70">{label}</p>
        <p className="bg-gradient-to-r from-[#0b2a6f] to-[#2b8de8] bg-clip-text text-3xl font-semibold text-transparent">{value}</p>
        {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function toData(rec: Record<string, number>) {
  return Object.entries(rec).map(([name, value]) => ({ name, value }));
}

function ChartCard({ title, children, empty }: { title: string; children: React.ReactNode; empty?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{empty ? <UnavailableNote>{empty}</UnavailableNote> : <div className="h-60">{children}</div>}</CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  if (q.isPending)
    return (
      <>
        <PageHeader title="Overview" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <CardSkeleton key={i} rows={1} />)}</div>
      </>
    );
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const o = q.data;
  const perDay = Object.entries(o.incidents_per_day).map(([date, count]) => ({ date, count }));
  const priority = toData(o.by_approved_priority);
  const category = toData(o.by_approved_category);

  return (
    <>
      <PageHeader title="Overview" subtitle="Live counts from the local backend database." actions={o.synthetic_incidents > 0 ? <Badge tone="violet">{o.synthetic_incidents} synthetic demo incidents</Badge> : undefined} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total incidents" value={o.total_incidents} />
        <Stat label="New" value={o.by_status.NEW ?? 0} />
        <Stat label="Triage pending / review" value={(o.by_status.TRIAGE_PENDING ?? 0) + (o.by_status.NEEDS_REVIEW ?? 0)} />
        <Stat label="Assigned" value={(o.by_status.ASSIGNED ?? 0) + (o.by_status.REASSIGNED ?? 0)} />
        <Stat label="Accepted" value={o.by_status.ACCEPTED ?? 0} />
        <Stat label="Unassigned" value={o.unassigned} />
        <Stat label="Manual override rate" value={o.override_rate === null ? "n/a" : pct(o.override_rate)} hint={o.override_rate === null ? "No assignments yet" : `${o.overrides_total} of ${o.assignments_total} assignments`} />
        <Stat label="Predictions recorded" value={o.predictions_total} hint={`Models: ${o.model_status}`} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ChartCard title="Priority mix (approved)" empty={priority.length === 0 ? "No approved priorities yet." : undefined}>
          <ResponsiveContainer>
            <PieChart>
              <Pie data={priority} dataKey="value" nameKey="name" innerRadius={50} outerRadius={85} label>
                {priority.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Category distribution (approved)" empty={category.length === 0 ? "No approved categories yet." : undefined}>
          <ResponsiveContainer>
            <BarChart data={category}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="value" fill="#2b7de0" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Calibrated-confidence distribution" empty={o.confidence_histogram.length === 0 ? "No prediction with a calibrated confidence has been recorded yet." : undefined}>
          <ResponsiveContainer>
            <BarChart data={o.confidence_histogram}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="bin" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#5eead4" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Incidents created per day" empty={perDay.length === 0 ? "No incidents yet." : undefined}>
          <ResponsiveContainer>
            <LineChart data={perDay}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Line dataKey="count" stroke="#7c6fe0" strokeWidth={2} dot />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
      <div className="mt-4 space-y-2">
        <UnavailableNote>Per-day assignment trends are not exposed by the API yet; only incident-creation volume is shown.</UnavailableNote>
        <p className="text-xs text-slate-500">{o.note}</p>
      </div>
    </>
  );
}
