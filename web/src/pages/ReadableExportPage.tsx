import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import type { ExportSection } from "../api/types";
import { Badge, Button, Card, Dl, ErrorState, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/useApi";

/**
 * The readable copy of the customer's own data (S8.5c). All wording, money and dates arrive
 * already formatted by the server, in the customer's language; this page only lays them out
 * and prints. The JSON file stays on the Privacy page.
 */

function Section({
  section,
  labels,
  provisional,
}: {
  section: ExportSection;
  labels: { why: string; howlong: string; empty: string; history: string };
  provisional: string | null;
}) {
  return (
    <Card className="print-section p-5">
      <section aria-labelledby={`export-${section.key}`} data-testid={`export-${section.key}`}>
        <h2 id={`export-${section.key}`} className="font-montserrat text-base font-semibold text-foreground">
          {section.title}
        </h2>
        {section.purpose && (
          <p className="mt-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{labels.why}:</span> {section.purpose}
          </p>
        )}
        {section.retention && (
          <p className="mt-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{labels.howlong}:</span> {section.retention}
            {section.retention_provisional && provisional && (
              <Badge tone="warning" className="ml-2">
                {provisional}
              </Badge>
            )}
          </p>
        )}
        {section.records.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">{labels.empty}</p>
        ) : (
          <ul className="mt-3 divide-y divide-border">
            {section.records.map((fields, i) => (
              <li key={i} className="py-3">
                <Dl items={fields.map((f) => [f.label, f.value])} />
              </li>
            ))}
          </ul>
        )}
        {section.history && section.history.length > 0 && (
          <div className="mt-3">
            <h3 className="text-sm font-semibold text-foreground">{labels.history}</h3>
            <ul className="mt-1 divide-y divide-border">
              {section.history.map((fields, i) => (
                <li key={i} className="py-2">
                  <Dl items={fields.map((f) => [f.label, f.value])} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </Card>
  );
}

export function ReadableExportPage() {
  const { data, error, loading, reload } = useApi(() => api.readableExport(), []);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error} onRetry={reload} />;

  return (
    <div lang={data.language === "hi" ? "hi" : "en"}>
      <div className="no-print mb-2">
        <Link
          to="/privacy"
          className="text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground"
        >
          {data.labels.back}
        </Link>
      </div>
      <PageHeader
        title={data.title}
        subtitle={`${data.generated}. ${data.tz_note}`}
        actions={
          <span className="no-print">
            <Button variant="outline" onClick={() => window.print()}>
              {data.labels.print}
            </Button>
          </span>
        }
      />
      <div className="space-y-4">
        {data.sections.map((s) => (
          <Section key={s.key} section={s} labels={data.labels} provisional={data.provisional_label} />
        ))}
        <footer className="border-t border-border pt-3 text-sm text-foreground" data-testid="export-contact">
          <span className="font-medium">{data.contact.label}:</span>{" "}
          {[data.contact.name, data.contact.email].filter(Boolean).join(", ")}
          {data.contact.name || data.contact.email ? ". " : ""}
          {data.contact.response_text}
        </footer>
      </div>
    </div>
  );
}
