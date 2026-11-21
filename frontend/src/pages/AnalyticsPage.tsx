import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CardSkeleton, EmptyState, ErrorState, PageHeader } from "@/components/common";
import { DemoBanner } from "@/components/triage/AiPanels";
import { Badge, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui/primitives";
import { api } from "@/lib/endpoints";
import type { Evaluations } from "@/lib/schemas";
import { num, pct } from "@/lib/utils";

type Experiment = Evaluations["experiments"][number];

function ComparisonTable({ exp }: { exp: Experiment }) {
  const showTopK = exp.rows.some((r) => r.test?.top1 != null);
  const showHp = exp.rows.some((r) => r.test?.high_priority_recall != null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-left text-sm">
        <caption className="sr-only">Model comparison for {exp.experiment}</caption>
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-3">Model</th>
            <th scope="col" className="px-3">Type</th>
            <th scope="col" className="px-3">Val macro F1</th>
            <th scope="col" className="px-3">Test macro F1</th>
            <th scope="col" className="px-3">Weighted F1</th>
            <th scope="col" className="px-3">Accuracy</th>
            {showTopK && <th scope="col" className="px-3">Top-3</th>}
            {showHp && <th scope="col" className="px-3">High-priority recall</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {exp.rows.map((r) => (
            <tr key={r.name} className={r.name === exp.selected ? "bg-sky-50/60" : undefined}>
              <th scope="row" className="py-2 pr-3 font-medium">
                {r.name}
                {r.name === exp.selected && <Badge tone="sky" className="ml-2">selected on validation</Badge>}
                {r.name === exp.deploy_choice && r.name !== exp.selected && <Badge tone="teal" className="ml-2">deployed</Badge>}
              </th>
              <td className="px-3 text-xs text-slate-500">{r.kind}</td>
              <td className="px-3">{num(r.val_macro_f1)}</td>
              <td className="px-3">{num(r.test?.macro_f1)}</td>
              <td className="px-3">{num(r.test?.weighted_f1)}</td>
              <td className="px-3">{num(r.test?.accuracy)}</td>
              {showTopK && <td className="px-3">{num(r.test?.top3)}</td>}
              {showHp && <td className="px-3">{num(r.test?.high_priority_recall)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  const max = Math.max(1, ...matrix.flat());
  return (
    <div className="overflow-x-auto">
      <table className="text-xs" aria-label="Confusion matrix (rows: true, columns: predicted)">
        <thead>
          <tr>
            <th scope="col" className="p-1 text-left text-slate-400">true ↓ / pred →</th>
            {labels.map((l) => <th key={l} scope="col" className="max-w-24 truncate p-1 font-medium" title={l}>{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <th scope="row" className="max-w-32 truncate p-1 text-left font-medium" title={labels[i]}>{labels[i]}</th>
              {row.map((v, j) => (
                <td key={j} className="p-1 text-center" style={{ background: `rgba(125, 211, 252, ${(v / max) * 0.85})` }}>{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExperimentView({ exp }: { exp: Experiment }) {
  const detail = exp.selected_detail;
  const support = (detail?.per_class ?? []).map((p) => ({ name: p.label, support: p.support ?? 0 })).sort((a, b) => b.support - a.support);
  const bins = exp.calibration?.reliability_bins ?? [];
  const ds = exp.dataset ?? {};
  return (
    <div className="space-y-6">
      {exp.is_demo && <DemoBanner message="These results come from SYNTHETIC demo data and are not evidence of real-world performance." />}
      <Card>
        <CardHeader>
          <CardTitle>Model comparison — {exp.experiment}</CardTitle>
          <Badge tone={exp.is_demo ? "violet" : "green"}>{exp.is_demo ? "Synthetic demo" : "Real data"}</Badge>
        </CardHeader>
        <CardContent className="space-y-3">
          {exp.finding && <p className="rounded-xl bg-teal-50 px-3 py-2 text-xs text-teal-900">{exp.finding}</p>}
          <ComparisonTable exp={exp} />
          <dl className="grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
            <div><dt className="text-slate-400">Provenance</dt><dd>{exp.provenance}</dd></div>
            <div><dt className="text-slate-400">Seed</dt><dd>{exp.seed ?? "—"}</dd></div>
            <div><dt className="text-slate-400">Dataset fingerprint</dt><dd className="font-mono">{String(ds.fingerprint ?? "—")}</dd></div>
            <div><dt className="text-slate-400">Rows</dt><dd>{String(ds.rows ?? ds.rows_total ?? "—")}</dd></div>
          </dl>
          {exp.split != null && <p className="text-xs text-slate-500">Split: {typeof exp.split === "string" ? exp.split : JSON.stringify(exp.split)}</p>}
        </CardContent>
      </Card>

      {detail?.confusion && (
        <Card>
          <CardHeader><CardTitle>Confusion matrix — {exp.selected}</CardTitle></CardHeader>
          <CardContent><ConfusionMatrix labels={detail.confusion.labels} matrix={detail.confusion.matrix} /></CardContent>
        </Card>
      )}
      {detail && !detail.confusion && <EmptyState title="Confusion matrix omitted" hint="Too many classes to display legibly; see the report JSON." />}

      {detail && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Per-class performance — {exp.selected}</CardTitle></CardHeader>
            <CardContent className="max-h-72 overflow-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-slate-500"><tr><th scope="col">Class</th><th scope="col">Precision</th><th scope="col">Recall</th><th scope="col">F1</th><th scope="col">Support</th></tr></thead>
                <tbody>
                  {detail.per_class.map((p) => (
                    <tr key={p.label} className="border-t border-slate-50"><th scope="row" className="py-1 text-left font-medium">{p.label}</th><td>{num(p.precision)}</td><td>{num(p.recall)}</td><td>{num(p.f1)}</td><td>{p.support}</td></tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Class imbalance (test support)</CardTitle></CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer>
                <BarChart data={support.slice(0, 15)} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis type="number" allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="support" fill="#c4b5fd" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {exp.calibration && bins.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Calibration reliability ({exp.calibration.method ?? "calibrated"})</CardTitle>
            <span className="text-xs text-slate-500">ECE {num(exp.calibration.ece_top_label)} · Brier {num(exp.calibration.brier)}</span>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer>
              <LineChart data={bins}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bin" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 1]} tickFormatter={(v) => pct(v, 0)} />
                <Tooltip formatter={(v) => pct(Number(v))} />
                <Line dataKey="confidence" name="Mean confidence" stroke="#7dd3fc" strokeWidth={2} />
                <Line dataKey="accuracy" name="Observed accuracy" stroke="#7c6fe0" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function AnalyticsPage() {
  const evals = useQuery({ queryKey: ["evaluations"], queryFn: api.evaluations });
  const metrics = useQuery({ queryKey: ["model-metrics"], queryFn: api.modelMetrics });
  const [sel, setSel] = useState("");

  if (evals.isPending) return <CardSkeleton rows={6} />;
  if (evals.isError) return <ErrorState error={evals.error} onRetry={() => evals.refetch()} />;

  const exps = evals.data.experiments;
  const active = exps.find((e) => e.experiment === sel) ?? exps[0];

  return (
    <>
      <PageHeader title="Analytics" subtitle="Measured offline results on held-out test splits. Nothing here is computed in the browser." />
      <p className="mb-4 text-xs text-slate-500">{evals.data.message}</p>
      {!active ? (
        <EmptyState title="No evaluation results available" hint="Run the ML pipeline (ml/) to generate result files." />
      ) : (
        <>
          <div className="mb-4 max-w-md">
            <Select aria-label="Experiment" value={active.experiment} onChange={(e) => setSel(e.target.value)}>
              {exps.map((e) => (
                <option key={e.experiment} value={e.experiment}>{e.experiment} — {e.is_demo ? "SYNTHETIC DEMO" : "real"}</option>
              ))}
            </Select>
          </div>
          <ExperimentView exp={active} />
        </>
      )}
      <Card className="mt-6">
        <CardHeader><CardTitle>Registered model versions</CardTitle></CardHeader>
        <CardContent className="text-sm">
          {metrics.isPending ? <CardSkeleton rows={1} /> : metrics.isError ? <ErrorState error={metrics.error} /> : metrics.data.models.length === 0 ? (
            <p className="text-slate-500">{metrics.data.message}</p>
          ) : (
            <ul className="space-y-1">
              {metrics.data.models.map((m) => (
                <li key={m.id} className="flex flex-wrap justify-between gap-2"><span>{m.name} <span className="font-mono text-xs text-slate-500">{m.version}</span></span><Badge tone="slate">{m.status}</Badge></li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}
