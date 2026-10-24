import { useMemo } from "react";
import { useAuth } from "../auth/session";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { manualMarkdown, renderMarkdown } from "../manual";
import { roleLabel } from "../lib/roles";

export function HelpPage() {
  const { me } = useAuth();
  const role = me?.role ?? "";
  const html = useMemo(() => {
    const md = manualMarkdown(role);
    return md ? renderMarkdown(md) : null;
  }, [role]);

  return (
    <>
      <PageHeader title="Help" subtitle={`The manual for your role: ${roleLabel(role)}.`} />
      {html ? (
        <Card className="p-5 sm:p-8">
          {/* Sanitised with DOMPurify in renderMarkdown. */}
          <article className="manual" dangerouslySetInnerHTML={{ __html: html }} />
        </Card>
      ) : (
        <EmptyState title="No manual for this role yet" />
      )}
    </>
  );
}
