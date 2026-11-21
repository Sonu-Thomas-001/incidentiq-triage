import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { Status } from "@/lib/schemas";
import { Badge, Card, Skeleton } from "./ui/primitives";
import { Button } from "./ui/button";

const STATUS_TONE: Record<string, "slate" | "sky" | "amber" | "violet" | "green" | "rose"> = {
  NEW: "slate",
  TRIAGE_PENDING: "sky",
  NEEDS_REVIEW: "amber",
  ASSIGNED: "violet",
  ACCEPTED: "green",
  REASSIGNED: "rose",
};

export function StatusChip({ status }: { status: Status | string }) {
  return <Badge tone={STATUS_TONE[status] ?? "slate"}>{status.replace("_", " ")}</Badge>;
}

export function PriorityChip({ priority }: { priority?: string | null }) {
  if (!priority) return <span className="text-slate-400">—</span>;
  const tone = priority === "P1" ? "rose" : priority === "P2" ? "amber" : priority === "P3" ? "sky" : "slate";
  return <Badge tone={tone}>{priority}</Badge>;
}

export function SyntheticBadge() {
  return (
    <Badge tone="violet" title="Synthetic demo data, not a real incident">
      Synthetic demo
    </Badge>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="relative mb-6 flex flex-wrap items-center justify-between gap-3 overflow-hidden rounded-2xl bg-gradient-to-r from-[#0b2a6f] via-[#1d5fd8] to-[#5bb8f7] px-6 py-5 shadow-lg shadow-blue-700/20">
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full bg-white/15 blur-2xl" />
      <div className="relative">
        <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-blue-100">{subtitle}</p>}
      </div>
      <div className="relative">{actions}</div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center">
      <Inbox className="h-8 w-8 text-blue-300" aria-hidden />
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint && <p className="max-w-md text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "STALE_VERSION") return "This incident changed since you loaded it. Refresh and try again.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-2xl border border-rose-100 bg-rose-50/70 p-4 text-sm text-rose-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Could not load data</p>
        <p className="text-xs">{errorMessage(error)}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw className="h-3 w-3" /> Retry
        </Button>
      )}
    </div>
  );
}

export function UnavailableNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-800">
      <strong>Unavailable:</strong> {children}
    </div>
  );
}

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <Card className="space-y-3 p-5" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </Card>
  );
}
