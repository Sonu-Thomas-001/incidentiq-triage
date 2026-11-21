import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { errorMessage, PageHeader, StatusChip } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/endpoints";
import type { IncidentDetail } from "@/lib/schemas";

export const incidentFormSchema = z.object({
  title: z.string().trim().min(5, "Short description needs at least 5 characters").max(200, "Keep it under 200 characters"),
  description: z.string().trim().min(10, "Describe the problem in at least 10 characters").max(8000, "Description is too long"),
  service: z.string().max(100).optional(),
  impact: z.coerce.number().int().min(1).max(3),
  urgency: z.coerce.number().int().min(1).max(3),
  location: z.string().max(100).optional(),
  affected_users: z.string().max(100).optional(),
});
export type IncidentFormValues = z.input<typeof incidentFormSchema>;

// The backend stores only title + description, so optional metadata is appended as plain text.
export function composeDescription(v: z.output<typeof incidentFormSchema>): string {
  const meta = [
    v.service && `Service: ${v.service}`,
    v.location && `Location: ${v.location}`,
    v.affected_users && `Affected users: ${v.affected_users}`,
  ].filter(Boolean);
  return meta.length ? `${v.description}\n\n---\n${meta.join("\n")}` : v.description;
}

const LEVELS = [
  { v: 1, label: "1 – High" },
  { v: 2, label: "2 – Medium" },
  { v: 3, label: "3 – Low" },
];

export default function CreateIncidentPage() {
  const qc = useQueryClient();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<IncidentFormValues, unknown, z.output<typeof incidentFormSchema>>({
    resolver: zodResolver(incidentFormSchema),
    defaultValues: { impact: 2, urgency: 2 },
  });

  const create = useMutation({
    mutationFn: (v: z.output<typeof incidentFormSchema>) =>
      api.createIncident({ title: v.title, description: composeDescription(v) }),
    onSuccess: () => {
      toast.success("Incident created");
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const created: IncidentDetail | undefined = create.data;
  const vals = create.variables;

  return (
    <>
      <PageHeader title="Create Incident" subtitle="The original text is stored immutably; triage recommendations are kept separate." />
      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardContent>
            <form
              noValidate
              className="space-y-4 pt-2"
              onSubmit={handleSubmit((v) => create.mutate(v))}
              aria-label="Create incident form"
            >
              <Field label="Short description" htmlFor="title" error={errors.title?.message}>
                <Input id="title" {...register("title")} />
              </Field>
              <Field label="Detailed description" htmlFor="description" error={errors.description?.message}>
                <Textarea id="description" rows={6} {...register("description")} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Service" htmlFor="service" hint="Optional" error={errors.service?.message}>
                  <Input id="service" placeholder="e.g. VPN" {...register("service")} />
                </Field>
                <Field label="Impact" htmlFor="impact">
                  <Select id="impact" {...register("impact")}>
                    {LEVELS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
                  </Select>
                </Field>
                <Field label="Urgency" htmlFor="urgency">
                  <Select id="urgency" {...register("urgency")}>
                    {LEVELS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
                  </Select>
                </Field>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Location" htmlFor="location" hint="Optional">
                  <Input id="location" {...register("location")} />
                </Field>
                <Field label="Affected users" htmlFor="affected_users" hint="Optional">
                  <Input id="affected_users" {...register("affected_users")} />
                </Field>
              </div>
              <p className="text-xs text-slate-500">
                Service, location and affected users are appended to the description (the API has no separate fields).
                Impact and urgency are used by the priority policy at triage time.
              </p>
              <div className="flex gap-2">
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? "Creating…" : "Create incident"}
                </Button>
                <Button variant="ghost" onClick={() => { reset(); create.reset(); }}>
                  Reset
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card aria-live="polite">
          <CardHeader>
            <CardTitle>Created incident</CardTitle>
          </CardHeader>
          <CardContent>
            {created ? (
              <div className="space-y-3 text-sm">
                <p className="flex items-center gap-2 font-medium text-emerald-700">
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Saved
                </p>
                <p className="font-medium">{created.title}</p>
                <div className="flex items-center gap-2">
                  <StatusChip status={created.status} />
                  <span className="font-mono text-xs text-slate-400">{created.id.slice(0, 8)}</span>
                </div>
                <Button asChild className="w-full">
                  <Link to={`/incidents/${created.id}?impact=${vals?.impact ?? ""}&urgency=${vals?.urgency ?? ""}`}>
                    Open triage workspace
                  </Link>
                </Button>
              </div>
            ) : (
              <p className="text-sm text-slate-500">Submit the form to see the created incident and start triage.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
