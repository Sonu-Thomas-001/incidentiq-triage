import enum


class Role(enum.StrEnum):
    REPORTER = "REPORTER"
    TRIAGE_ANALYST = "TRIAGE_ANALYST"
    SUPPORT_ENGINEER = "SUPPORT_ENGINEER"
    ADMIN = "ADMIN"


class IncidentStatus(enum.StrEnum):
    NEW = "NEW"
    TRIAGE_PENDING = "TRIAGE_PENDING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REASSIGNED = "REASSIGNED"


class Priority(enum.StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class PredictionStatus(enum.StrEnum):
    NOT_READY = "NOT_READY"
    DEMO = "DEMO"
    MODEL = "MODEL"


class AssignmentStatus(enum.StrEnum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class LabelType(enum.StrEnum):
    CATEGORY = "CATEGORY"
    PRIORITY = "PRIORITY"
    TEAM = "TEAM"


class WorkflowKind(enum.StrEnum):
    TRIAGE = "TRIAGE"
    APPROVAL = "APPROVAL"


class WorkflowRunStatus(enum.StrEnum):
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SyncStatus(enum.StrEnum):
    PREVIEWED = "PREVIEWED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
