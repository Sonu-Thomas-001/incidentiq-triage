import { z } from "zod";
import { request } from "./api";
import {
  auditEventSchema,
  evaluationsSchema,
  incidentDetailSchema,
  incidentSchema,
  modelMetricsSchema,
  overviewSchema,
  pageOf,
  teamSchema,
  tokenSchema,
  userSchema,
  workflowConfigSchema,
  workflowRunSchema,
} from "./schemas";

export interface IncidentFilters {
  page?: number;
  page_size?: number;
  status?: string;
  priority?: string;
  q?: string;
  team_id?: string;
}

const looseRecord = z.record(z.string(), z.unknown());

export const api = {
  login: (email: string, password: string) =>
    request("/auth/login", { method: "POST", body: { email, password }, schema: tokenSchema, auth: false }),
  me: () => request("/auth/me", { schema: userSchema }),
  teams: () => request("/teams", { schema: z.array(teamSchema) }),

  listIncidents: (f: IncidentFilters) =>
    request("/incidents", { query: { ...f }, schema: pageOf(incidentSchema) }),
  getIncident: (id: string) => request(`/incidents/${id}`, { schema: incidentDetailSchema }),
  createIncident: (body: { title: string; description: string }) =>
    request("/incidents", { method: "POST", body, schema: incidentDetailSchema }),
  audit: (id: string, page = 1) =>
    request(`/incidents/${id}/audit`, { query: { page, page_size: 100 }, schema: pageOf(auditEventSchema) }),
  queue: (teamId: string, f: { page?: number; page_size?: number; status?: string }) =>
    request(`/teams/${teamId}/queue`, { query: { ...f }, schema: pageOf(incidentSchema) }),

  accept: (id: string, expected_version: number) =>
    request(`/incidents/${id}/accept`, { method: "POST", body: { expected_version }, schema: incidentDetailSchema }),
  assign: (
    id: string,
    body: { expected_version: number; team_id: string; priority?: string; category?: string; reason?: string; prediction_id?: string },
  ) => request(`/incidents/${id}/assign`, { method: "POST", body, schema: incidentDetailSchema }),
  override: (
    id: string,
    body: { expected_version: number; team_id: string; priority?: string; category?: string; reason: string },
  ) => request(`/incidents/${id}/override`, { method: "POST", body, schema: incidentDetailSchema }),

  runWorkflow: (
    id: string,
    body: { expected_version: number; impact?: number; urgency?: number; use_gemini?: boolean; external_data_consent?: boolean },
  ) => request(`/workflow/incidents/${id}/run`, { method: "POST", body, schema: workflowRunSchema }),
  approveWorkflow: (
    id: string,
    body: { expected_version: number; team_id: string; priority?: string; category?: string; reason?: string; run_id?: string },
  ) => request(`/workflow/incidents/${id}/approve`, { method: "POST", body, schema: looseRecord }),
  workflowRuns: (id: string) => request(`/workflow/incidents/${id}/runs`, { schema: z.array(workflowRunSchema) }),
  workflowConfig: () => request("/workflow/config", { schema: workflowConfigSchema }),

  overview: () => request("/analytics/overview", { schema: overviewSchema }),
  modelMetrics: () => request("/models/metrics", { schema: modelMetricsSchema }),
  evaluations: () => request("/models/evaluations", { schema: evaluationsSchema }),

  snHealth: () => request("/integrations/servicenow/health", { schema: looseRecord }),
  snMappings: () => request("/integrations/servicenow/team-mappings", { schema: z.array(looseRecord) }),
  snSetMapping: (team_id: string, servicenow_group_sys_id: string | null) =>
    request("/integrations/servicenow/team-mappings", {
      method: "POST",
      body: { team_id, servicenow_group_sys_id },
      schema: looseRecord,
    }),
  snSyncPreview: (id: string) =>
    request(`/integrations/servicenow/incidents/${id}/sync/preview`, { method: "POST", schema: looseRecord }),
  snSyncApprove: (id: string, body: { preview_id: string; confirm: boolean; confirm_instance_host: string }) =>
    request(`/integrations/servicenow/incidents/${id}/sync/approve`, { method: "POST", body, schema: looseRecord }),
};
