import { z } from "zod";

// Schemas validate the fields the UI relies on; unknown extra fields are tolerated.
export const ROLES = ["REPORTER", "TRIAGE_ANALYST", "SUPPORT_ENGINEER", "ADMIN"] as const;
export type Role = (typeof ROLES)[number];

export const STATUSES = [
  "NEW",
  "TRIAGE_PENDING",
  "NEEDS_REVIEW",
  "ASSIGNED",
  "ACCEPTED",
  "REASSIGNED",
] as const;
export type Status = (typeof STATUSES)[number];

export const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;

export const tokenSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
});

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: z.enum(ROLES),
  team_id: z.string().nullable().optional(),
  is_synthetic: z.boolean().optional(),
});
export type User = z.infer<typeof userSchema>;

export const teamSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  is_synthetic: z.boolean().optional(),
});
export type Team = z.infer<typeof teamSchema>;

export const incidentSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  reporter_id: z.string(),
  status: z.enum(STATUSES),
  approved_priority: z.string().nullable().optional(),
  approved_category: z.string().nullable().optional(),
  is_synthetic: z.boolean(),
  version: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Incident = z.infer<typeof incidentSchema>;

export const assignmentSchema = z.object({
  id: z.string(),
  team_id: z.string(),
  assigned_by: z.string(),
  status: z.string(),
  is_override: z.boolean(),
  reason: z.string().nullable().optional(),
  accepted_by: z.string().nullable().optional(),
  accepted_at: z.string().nullable().optional(),
  created_at: z.string(),
});

export const predictionSchema = z.object({
  id: z.string(),
  status: z.string(),
  predicted_category: z.string().nullable().optional(),
  predicted_priority: z.string().nullable().optional(),
  predicted_team_id: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  explanation: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
});

export const incidentDetailSchema = incidentSchema.extend({
  current_assignment: assignmentSchema.nullable().optional(),
  latest_prediction: predictionSchema.nullable().optional(),
});
export type IncidentDetail = z.infer<typeof incidentDetailSchema>;

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number(),
    page: z.number(),
    page_size: z.number(),
  });

export const auditEventSchema = z.object({
  id: z.string(),
  incident_id: z.string(),
  actor_id: z.string().nullable().optional(),
  event_type: z.string(),
  from_status: z.string().nullable().optional(),
  to_status: z.string().nullable().optional(),
  details: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
});
export type AuditEvent = z.infer<typeof auditEventSchema>;

export const overviewSchema = z.object({
  total_incidents: z.number(),
  synthetic_incidents: z.number(),
  by_status: z.record(z.string(), z.number()),
  by_approved_priority: z.record(z.string(), z.number()),
  by_assigned_team: z.record(z.string(), z.number()),
  unassigned: z.number(),
  model_status: z.string(),
  note: z.string(),
  by_approved_category: z.record(z.string(), z.number()).default({}),
  incidents_per_day: z.record(z.string(), z.number()).default({}),
  assignments_total: z.number().default(0),
  overrides_total: z.number().default(0),
  override_rate: z.number().nullable().default(null),
  predictions_total: z.number().default(0),
  confidence_histogram: z.array(z.object({ bin: z.string(), count: z.number() })).default([]),
});
export type Overview = z.infer<typeof overviewSchema>;

export const modelMetricsSchema = z.object({
  status: z.string(),
  message: z.string(),
  models: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      version: z.string(),
      status: z.string(),
      metrics: z.record(z.string(), z.unknown()).nullable().optional(),
      trained_at: z.string().nullable().optional(),
    }),
  ),
});

const metricBlock = z.object({
  n: z.number().nullable().optional(),
  accuracy: z.number().nullable().optional(),
  macro_f1: z.number().nullable().optional(),
  macro_precision: z.number().nullable().optional(),
  macro_recall: z.number().nullable().optional(),
  weighted_f1: z.number().nullable().optional(),
  top1: z.number().nullable().optional(),
  top3: z.number().nullable().optional(),
  high_priority_recall: z.number().nullable().optional(),
});
export type MetricBlock = z.infer<typeof metricBlock>;

export const evaluationsSchema = z.object({
  status: z.string(),
  message: z.string(),
  experiments: z.array(
    z.object({
      experiment: z.string(),
      task: z.string(),
      provenance: z.string(),
      is_demo: z.boolean(),
      dataset: z.record(z.string(), z.unknown()).nullable().optional(),
      split: z.unknown().optional(),
      seed: z.number().nullable().optional(),
      finding: z.string().nullable().optional(),
      selected: z.string().nullable().optional(),
      deploy_choice: z.string().nullable().optional(),
      rows: z.array(
        z.object({
          name: z.string(),
          kind: z.string(),
          feature_set: z.string().nullable().optional(),
          algorithm: z.string().nullable().optional(),
          val_macro_f1: z.number().nullable().optional(),
          test: metricBlock.nullable().optional(),
        }),
      ),
      selected_detail: z
        .object({
          per_class: z.array(
            z.object({
              label: z.string(),
              precision: z.number().nullable().optional(),
              recall: z.number().nullable().optional(),
              f1: z.number().nullable().optional(),
              support: z.number().nullable().optional(),
            }),
          ),
          confusion: z
            .object({ labels: z.array(z.string()), matrix: z.array(z.array(z.number())) })
            .nullable(),
        })
        .nullable()
        .optional(),
      calibration: z
        .object({
          method: z.string().nullable().optional(),
          ece_top_label: z.number().nullable().optional(),
          brier: z.number().nullable().optional(),
          reliability_bins: z
            .array(z.object({ bin: z.string(), n: z.number(), confidence: z.number(), accuracy: z.number() }))
            .nullable()
            .optional(),
        })
        .nullable()
        .optional(),
    }),
  ),
});
export type Evaluations = z.infer<typeof evaluationsSchema>;

export const workflowRunSchema = z.object({
  run_id: z.string(),
  kind: z.string(),
  status: z.string(),
  reused: z.boolean(),
  outcome: z.string().nullable().optional(),
  prediction_id: z.string().nullable().optional(),
  input_issues: z.array(z.unknown()).nullable().optional(),
  priority_inputs: z.record(z.string(), z.unknown()).nullable().optional(),
  ml: z.record(z.string(), z.unknown()).nullable().optional(),
  explanation: z.record(z.string(), z.unknown()).nullable().optional(),
  assist: z.record(z.string(), z.unknown()).nullable().optional(),
  routing: z.record(z.string(), z.unknown()).nullable().optional(),
  review: z.record(z.string(), z.unknown()).nullable().optional(),
  trace: z.array(z.unknown()).nullable().optional(),
  created_at: z.string().nullable().optional(),
  incident: incidentSchema.nullable().optional(),
});
export type WorkflowRun = z.infer<typeof workflowRunSchema>;

export const workflowConfigSchema = z.record(z.string(), z.unknown());

export const serviceNowHealthSchema = z.record(z.string(), z.unknown());
export const teamMappingsSchema = z.unknown();
