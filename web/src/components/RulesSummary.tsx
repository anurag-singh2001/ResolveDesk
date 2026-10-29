import { api } from "../api/endpoints";
import type { CategoryRule, RuleLine, RuleSetting } from "../api/types";
import { useApi } from "../lib/useApi";
import { Badge, Card, ErrorState, Loading, numClass, tableClass, tableWrapClass, tdClass, thClass } from "./ui";

/** Every sentence and figure here comes from the server (built in code from the tenant's rules);
 * this component only lays it out. */
export function RulesSummarySection({ staff }: { staff: boolean }) {
  const { data, error, loading, reload } = useApi(() => api.rulesSummary(), [staff]);

  return (
    <Card className="mb-6 p-5 sm:p-6">
      <section aria-labelledby="rules-title" id="rules">
        <h2 id="rules-title" className="font-montserrat text-lg font-semibold text-foreground">
          Rules in plain words
        </h2>
        {loading && <Loading />}
        {error != null && <ErrorState error={error} onRetry={reload} />}
        {data && (
          <>
            <p className="mt-1 text-sm text-muted-foreground" data-testid="rules-in-force">
              {staff
                ? `${data.in_force_text} Rules pack: ${data.pack_name}, version ${data.pack_version}, updated ${data.pack_updated}.${
                    data.settings_updated ? ` Settings last changed ${data.settings_updated}.` : ""
                  }`
                : data.in_force_text}
            </p>
            <div className="mt-4 grid gap-5 md:grid-cols-2">
              {data.categories.map((c) => (
                <CategoryBlock key={c.category} rule={c} />
              ))}
            </div>
            {staff && data.settings.length > 0 && <SettingsTable rows={data.settings} />}
          </>
        )}
      </section>
    </Card>
  );
}

function CategoryBlock({ rule }: { rule: CategoryRule }) {
  return (
    <section aria-labelledby={`rule-${rule.category}`} data-testid={`rule-${rule.category}`}>
      <h3 id={`rule-${rule.category}`} className="font-montserrat text-sm font-semibold text-foreground">
        {rule.title}
      </h3>
      {rule.options.length > 0 && (
        <ul className="mt-1.5 space-y-2 text-sm text-foreground">
          {rule.options.map((o) => (
            <Line key={o.code} line={o} />
          ))}
        </ul>
      )}
      {rule.tiers.length > 0 && (
        <ul className="mt-1.5 space-y-2 border-l border-border pl-3 text-sm text-foreground">
          {rule.tiers.map((o) => (
            <Line key={`${o.min_minutes_late}`} line={o} heading={o.label} />
          ))}
        </ul>
      )}
      {rule.notes.map((n) => (
        <p key={n} className="mt-2 text-xs text-muted-foreground">
          {n}
        </p>
      ))}
    </section>
  );
}

function Line({ line, heading }: { line: RuleLine; heading?: string | null }) {
  return (
    <li>
      {heading && <span className="block text-xs font-medium text-muted-foreground">{heading}</span>}
      <span>{line.text}</span>
      {line.approval_text && <span className="ml-1 text-muted-foreground">{line.approval_text}</span>}
    </li>
  );
}

function show(value: unknown): string {
  if (Array.isArray(value) || (value && typeof value === "object")) return JSON.stringify(value);
  return String(value);
}

function SettingsTable({ rows }: { rows: RuleSetting[] }) {
  return (
    <div className="mt-6">
      <h3 className="font-montserrat text-sm font-semibold text-foreground">Settings behind these rules</h3>
      <div className={`${tableWrapClass} mt-2`}>
        <table className={tableClass}>
          <thead>
            <tr>
              <th className={thClass}>Setting</th>
              <th className={thClass}>Value</th>
              <th className={thClass}>Set by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} data-testid={`setting-${r.key}`}>
                <td className={`${tdClass} ${numClass}`}>{r.key}</td>
                <td className={`${tdClass} ${numClass} break-all`}>{show(r.value)}</td>
                <td className={tdClass}>
                  <Badge tone={r.source === "tenant_override" ? "info" : "muted"}>
                    {r.source === "tenant_override" ? "Tenant override" : "Pack default"}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
