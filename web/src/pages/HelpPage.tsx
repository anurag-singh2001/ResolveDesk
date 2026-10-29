import { useMemo } from "react";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { useApi } from "../lib/useApi";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { manualMarkdown, renderMarkdown } from "../manual";
import { roleLabel } from "../lib/roles";

export function HelpPage() {
  const { me } = useAuth();
  const role = me?.role ?? "";
  const { data: privacy } = useApi(() => api.privacyContact(), [role]);
  const html = useMemo(() => {
    const md = manualMarkdown(role);
    return md ? renderMarkdown(md) : null;
  }, [role]);

  return (
    <>
      <PageHeader title="Help" subtitle={`The manual for your role: ${roleLabel(role)}.`} />
      {privacy && privacy.email && (
        <Card className="mb-4 p-4">
          <h2 className="font-montserrat text-sm font-semibold text-foreground">Privacy contact</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            For questions about your personal data, or to make a privacy request: {privacy.name},{" "}
            <a className="font-medium text-foreground underline underline-offset-2 transition-colors duration-200 hover:text-brand" href={`mailto:${privacy.email}`}>
              {privacy.email}
            </a>
            . You can also report a problem on an order and choose the privacy request category.
          </p>
        </Card>
      )}
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
