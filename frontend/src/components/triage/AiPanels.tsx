import { AlertTriangle, Bot, Brain, Scale } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { pct } from "@/lib/utils";

type Rec = Record<string, unknown>;
const asRec = (v: unknown): Rec | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : null);
const asArr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const numv = (v: unknown): number | null => (typeof v === "number" ? v : null);

function Panel({
  icon,
  title,
  badge,
  tone,
  children,
}: {
  icon: ReactNode;
  title: string;
  badge: ReactNode;
  tone: "sky" | "teal" | "violet";
  children: ReactNode;
}) {
  const border = { sky: "border-t-blue-500", teal: "border-t-teal-400", violet: "border-t-violet-400" }[tone];
  return (
    <Card className={`border-t-4 ${border}`}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {icon} {title}
        </CardTitle>
        {badge}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">{children}</CardContent>
    </Card>
  );
}

export function DemoBanner({ message }: { message?: string }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-900">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>
        <strong>DEMO output.</strong> {message ?? "Produced by a model trained on synthetic data. Not evidence of real-world accuracy."}
      </span>
    </div>
  );
}

function Features({ features }: { features: unknown }) {
  const rows = asArr(features)
    .map(asRec)
    .filter((r): r is Rec => !!r)
    .slice(0, 6);
  if (!rows.length) return <p className="text-xs text-slate-500">No influential features reported.</p>;
  return (
    <ul className="space-y-1" aria-label="Influential features">
      {rows.map((r, i) => {
        const w = numv(r.contribution) ?? numv(r.weight) ?? numv(r.score);
        return (
          <li key={i} className="flex items-center justify-between rounded-lg bg-slate-50 px-2 py-1 text-xs">
            <span className="font-mono">{str(r.feature) ?? str(r.name) ?? "feature"}</span>
            {w !== null && <span className={w >= 0 ? "text-teal-700" : "text-rose-600"}>{w.toFixed(3)}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function TaskOutput({ label, out }: { label: string; out: Rec | null }) {
  if (!out || out.available === false) {
    return (
      <div className="rounded-xl bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-500">{label}</p>
        <p className="text-sm text-slate-600">Unavailable{str(out?.reason) ? ` — ${str(out?.reason)}` : ""}</p>
      </div>
    );
  }
  const conf = numv(out.confidence);
  const kind = str(out.confidence_kind);
  return (
    <div className="space-y-2 rounded-xl bg-sky-50/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="text-base font-semibold text-slate-900">{str(out.label) ?? "—"}</p>
        </div>
        <div className="text-right text-xs">
          {conf !== null ? (
            <>
              <p className="text-sm font-semibold">{pct(conf, 0)}</p>
              <p className="text-slate-500">{kind ?? "confidence"}</p>
            </>
          ) : (
            <p className="text-slate-500">No calibrated confidence</p>
          )}
        </div>
      </div>
      <p className="text-[11px] text-slate-500">
        Model {str(out.model_version) ?? "—"} · {str(out.provenance) ?? "unknown"} data · {str(out.explanation_method) ?? "no explanation method"}
      </p>
      <Features features={out.explanation_features} />
    </div>
  );
}

export function MlPanel({ ml }: { ml: Rec | null }) {
  const outputs = asRec(ml?.outputs);
  const demo = ml?.is_demo === true;
  return (
    <Panel
      icon={<Brain className="h-4 w-4 text-sky-600" aria-hidden />}
      title="ML prediction"
      tone="sky"
      badge={<Badge tone={demo ? "violet" : "sky"}>{str(ml?.status) ?? "UNKNOWN"}</Badge>}
    >
      {demo && <DemoBanner />}
      {ml?.status === "NOT_READY" && (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Trained models are not available on the server. No prediction was fabricated.
        </p>
      )}
      <TaskOutput label="Category" out={asRec(outputs?.category)} />
      <TaskOutput label="Team" out={asRec(outputs?.team)} />
      {str(ml?.disclaimer) && <p className="text-[11px] text-slate-500">{str(ml?.disclaimer)}</p>}
    </Panel>
  );
}

export function PolicyPanel({ ml, priorityInputs }: { ml: Rec | null; priorityInputs: Rec | null }) {
  const priority = asRec(asRec(ml?.outputs)?.priority);
  const available = priority?.available !== false && !!priority;
  return (
    <Panel
      icon={<Scale className="h-4 w-4 text-teal-600" aria-hidden />}
      title="Policy-derived priority"
      tone="teal"
      badge={<Badge tone="teal">Deterministic policy</Badge>}
    >
      {available ? (
        <>
          <p className="text-2xl font-semibold text-slate-900">{str(priority?.label) ?? "—"}</p>
          <p className="text-xs text-slate-600">
            Computed from impact × urgency by a fixed rule table — not a learned model and it has no probability.
          </p>
          {str(priority?.evidence) && <p className="text-xs text-slate-500">{str(priority?.evidence)}</p>}
        </>
      ) : (
        <p className="text-sm text-slate-600">
          Unavailable — {str(priority?.reason) ?? "impact and urgency were not provided"}.
        </p>
      )}
      {priorityInputs && (
        <p className="text-[11px] text-slate-500">
          Inputs: impact {String(asRec(priorityInputs.impact)?.value ?? "—")}, urgency {String(asRec(priorityInputs.urgency)?.value ?? "—")}
        </p>
      )}
    </Panel>
  );
}

export function GeminiPanel({ assist }: { assist: Rec | null }) {
  const status = str(assist?.status) ?? "NOT_REQUESTED";
  const output = asRec(assist?.output);
  const extracted = asRec(output?.extracted);
  const missing = asArr(output?.missing_information).filter((x): x is string => typeof x === "string");
  return (
    <Panel
      icon={<Bot className="h-4 w-4 text-violet-600" aria-hidden />}
      title="Optional Gemini summary"
      tone="violet"
      badge={<Badge tone="violet">LLM · {status}</Badge>}
    >
      {output ? (
        <>
          <p>{str(output.summary) || "No summary returned."}</p>
          {extracted && (
            <dl className="grid grid-cols-2 gap-1 text-xs">
              {Object.entries(extracted)
                .filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
                .map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-violet-50 px-2 py-1">
                    <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
                    <dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
                  </div>
                ))}
            </dl>
          )}
          {missing.length > 0 && (
            <div>
              <p className="text-xs font-medium text-slate-600">Suggested missing information</p>
              <ul className="list-disc pl-5 text-xs">
                {missing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <p className="text-slate-600">{str(assist?.message) ?? "Gemini assistance was not requested or is disabled."}</p>
      )}
      <p className="text-[11px] text-slate-500">
        {str(assist?.disclaimer) ?? "LLM text is a drafting aid. It is not model reasoning, has no confidence, and never influences routing."}
      </p>
    </Panel>
  );
}

export function RoutingPanel({ routing }: { routing: Rec | null }) {
  if (!routing) return null;
  const reasons = asArr(routing.reasons).filter((r): r is string => typeof r === "string");
  const checks = asArr(routing.checks).map(asRec).filter((c): c is Rec => !!c);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Routing rationale</CardTitle>
        <Badge tone="amber">{str(routing.decision) ?? "—"}</Badge>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-slate-600">
          Routing is {routing.routing_enabled ? "enabled" : "disabled"} (it is off until thresholds are validated). Auto-assign is
          never performed — an analyst must approve.
        </p>
        {reasons.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs" aria-label="Routing reasons">
            {reasons.map((r) => (
              <li key={r}>{r.replace(/_/g, " ")}</li>
            ))}
          </ul>
        )}
        <ul className="space-y-1 text-xs">
          {checks.map((c, i) => (
            <li key={i} className="flex items-center justify-between rounded-lg bg-slate-50 px-2 py-1">
              <span>{str(c.task)}{numv(c.threshold) !== null ? ` (threshold ${pct(numv(c.threshold), 0)})` : ""}</span>
              <Badge tone={c.passed ? "green" : "amber"}>{c.passed ? "passed" : str(c.reason)?.replace(/_/g, " ") ?? "not passed"}</Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function uncertaintyWarnings(ml: Rec | null, routing: Rec | null, inputIssues: unknown[]): string[] {
  const out: string[] = [];
  const outputs = asRec(ml?.outputs);
  if (ml?.is_demo === true) out.push("Model output is from synthetic demo data.");
  for (const task of ["category", "team"] as const) {
    const o = asRec(outputs?.[task]);
    if (o && o.available !== false && numv(o.confidence) === null) out.push(`No calibrated confidence for ${task}.`);
    const c = numv(o?.confidence);
    if (c !== null && c < 0.6) out.push(`Low ${task} confidence (${pct(c, 0)}).`);
  }
  for (const i of inputIssues) {
    const r = asRec(i);
    out.push(`Input issue: ${str(r?.message) ?? str(r?.code) ?? String(i)}`);
  }
  if (routing && routing.routing_enabled !== true) out.push("Routing is disabled; manual review is required.");
  return out;
}
