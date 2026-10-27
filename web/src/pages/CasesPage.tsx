import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { StageBadge } from "../components/badges";
import { Card, EmptyState, ErrorState, Loading, PageHeader, inputClass } from "../components/ui";
import { categoryLabel, formatDateTime, shortId } from "../lib/format";
import { formatPaise } from "../lib/money";
import { isStaff } from "../lib/roles";
import { STAGE_ORDER, stageMeta } from "../lib/stages";
import { useApi } from "../lib/useApi";

export function CasesPage() {
  const { me } = useAuth();
  const staff = isStaff(me?.role);
  const { data, error, loading, reload } = useApi(() => api.cases(200), []);
  const [stage, setStage] = useState("");

  const rows = (data ?? []).filter((c) => !stage || c.stage === stage);

  return (
    <>
      <PageHeader
        title={staff ? "Cases" : "My cases"}
        subtitle={staff ? "Every case you can see, newest first." : "Problems you've reported and where they are now."}
        actions={
          staff ? (
            <div className="flex items-center gap-2">
              <label htmlFor="stage-filter" className="text-sm text-muted-foreground">
                Stage
              </label>
              <select id="stage-filter" className={inputClass + " w-48"} value={stage} onChange={(e) => setStage(e.target.value)}>
                <option value="">All stages</option>
                {STAGE_ORDER.map((s) => (
                  <option key={s} value={s}>
                    {stageMeta(s).label}
                  </option>
                ))}
              </select>
            </div>
          ) : undefined
        }
      />
      {loading ? (
        <Loading label="Loading cases…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : rows.length === 0 ? (
        <EmptyState title={stage ? "No cases at this stage" : "No cases yet"}>
          {staff ? "Cases appear here when a customer reports a problem." : "If something goes wrong with an order, report it from the order page."}
        </EmptyState>
      ) : (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-border">
            {rows.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/cases/${c.id}`}
                  className="flex flex-col gap-2 px-4 py-3.5 transition-colors duration-200 hover:bg-muted focus-visible:bg-muted focus-visible:outline-none sm:flex-row sm:items-center sm:gap-4"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-foreground">{categoryLabel(c.category)}</span>
                      <span className="font-mono text-xs text-muted-foreground">{c.order_ref ?? shortId(c.transaction_id)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-sm text-muted-foreground">{c.message}</p>
                  </div>
                  <div className="flex items-center gap-3 sm:justify-end">
                    {c.amount_paise != null && <span className="font-mono text-sm tabular-nums text-foreground">{formatPaise(c.amount_paise)}</span>}
                    {c.created_at && <span className="hidden font-mono text-xs tabular-nums text-muted-foreground md:inline">{formatDateTime(c.created_at)}</span>}
                    <StageBadge stage={c.stage} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
