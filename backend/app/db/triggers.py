"""SQLite triggers enforcing immutability at the database level (defense in depth)."""

INCIDENT_TEXT_IMMUTABLE = """
CREATE TRIGGER IF NOT EXISTS trg_incidents_text_immutable
BEFORE UPDATE OF title, description, reporter_id, created_at ON incidents
WHEN OLD.title IS NOT NEW.title
  OR OLD.description IS NOT NEW.description
  OR OLD.reporter_id IS NOT NEW.reporter_id
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
  SELECT RAISE(ABORT, 'original incident text is immutable');
END
"""

AUDIT_NO_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'audit events are append-only');
END
"""

AUDIT_NO_DELETE = """
CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'audit events are append-only');
END
"""

DROP_ALL = [
    "DROP TRIGGER IF EXISTS trg_incidents_text_immutable",
    "DROP TRIGGER IF EXISTS trg_audit_events_no_update",
    "DROP TRIGGER IF EXISTS trg_audit_events_no_delete",
]
