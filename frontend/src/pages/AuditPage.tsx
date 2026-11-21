import { Link, useParams } from "react-router-dom";
import { AuditTimeline } from "@/components/AuditTimeline";
import { PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";

export default function AuditPage() {
  const { id = "" } = useParams();
  return (
    <>
      <PageHeader
        title="Audit Timeline"
        subtitle={`Incident ${id.slice(0, 8)} — creation, predictions, approvals, overrides and sync events.`}
        actions={
          <Button variant="outline" asChild>
            <Link to={`/incidents/${id}`}>Back to workspace</Link>
          </Button>
        }
      />
      <AuditTimeline incidentId={id} />
    </>
  );
}
