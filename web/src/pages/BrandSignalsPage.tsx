import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/endpoints";
import type { BrandSignal } from "../api/types";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { NO_DATA, formatBp, formatBpShort } from "../lib/dashboard";
import { useApi } from "../lib/useApi";

/** The segment view is built on its own branch; this is its agreed route. */
export const SEGMENTS_PATH = "/segments";

const STATUS: Record<BrandSignal["status"], { tone: "danger" | "success" | "neutral"; text: string }> = {
  drop: { tone: "danger", text: "Repeat rate dropped" },
  steady: { tone: "success", text: "Steady" },
  low_volume: { tone: "neutral", text: "Low volume" },
};

function BrandCard({ b }: { b: BrandSignal }) {
  const s = STATUS[b.status];
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">{b.name}</h2>
        <Badge tone={s.tone}>{s.text}</Badge>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Orders: {b.baseline_orders} before, {b.recent_orders} recently.
      </p>
      {b.status === "low_volume" ? (
        <p className="mt-2 text-sm text-foreground">
          Low volume: fewer than {b.min_orders} orders in a window, too few to show a trend.
        </p>
      ) : (
        <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">Before</dt>
            <dd className={numClass}>{formatBp(b.baseline_bp)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Recent</dt>
            <dd className={numClass}>{formatBp(b.recent_bp)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Drop</dt>
            <dd className={numClass}>{formatBp(b.drop_bp)}</dd>
          </div>
        </dl>
      )}
      {b.diagnosis && (
        <div className="mt-3 space-y-2 text-sm">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What the data shows</h3>
            <ul className="mt-1 list-disc pl-5">
              {(b.diagnosis.findings ?? []).map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Possible reasons (not confirmed)</h3>
            <ul className="mt-1 list-disc pl-5">
              {(b.diagnosis.hypotheses ?? []).map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Card>
  );
}

export function BrandSignalsPage() {
  const { data, error, loading, reload } = useApi(() => api.brandSignals(), []);
  // Low-volume brands are left out of the chart: a bar there would be a trend on too few orders.
  const rows = (data?.brands ?? [])
    .filter((b) => b.status !== "low_volume")
    .map((b) => ({ name: b.name, baseline_bp: b.baseline_bp, recent_bp: b.recent_bp }));
  const axis = { fill: "var(--muted-foreground)", fontSize: 11 };

  return (
    <div className="viz-root">
      <PageHeader
        title="Brand signals"
        subtitle="Repeat-customer rate for each brand across all its locations. Read-only."
        actions={
          <Link to="/growth" className="text-sm underline-offset-2 hover:underline">
            Location signals
          </Link>
        }
      />
      {loading && <Loading />}
      {error != null && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <div className="space-y-6">
          <p className="text-sm text-muted-foreground" data-testid="definition">
            {data.definition}
          </p>
          {data.brands.length === 0 ? (
            <EmptyState title="No brands in your scope" />
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                {data.brands.map((b) => (
                  <BrandCard key={b.brand_id} b={b} />
                ))}
              </div>
              {rows.length > 0 && (
                <Card className="p-4">
                  <h2 className="text-sm font-semibold text-foreground">Repeat rate by brand</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">Before and recent windows; brands with low volume are not charted.</p>
                  <div className="mt-3 h-56 w-full" data-testid="chart-brand-repeat">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
                        <YAxis tick={axis} tickLine={false} axisLine={false} width={48} tickFormatter={formatBpShort} domain={[0, 10000]} />
                        <Tooltip
                          contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--foreground)", fontSize: 12 }}
                          formatter={(v: unknown, name: string) => [typeof v === "number" ? formatBp(v) : NO_DATA, name]}
                        />
                        <Legend />
                        <Bar dataKey="baseline_bp" name="Before" fill="var(--viz-2)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                        <Bar dataKey="recent_bp" name="Recent" fill="var(--viz-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <details className="mt-2 text-xs" data-testid="table-brand-repeat">
                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Table view</summary>
                    <div className={`${tableWrapClass} mt-2`}>
                      <table className={tableClass}>
                        <caption className="sr-only">Repeat rate by brand</caption>
                        <thead>
                          <tr>
                            <th scope="col" className={thClass}>Brand</th>
                            <th scope="col" className={`${thClass} text-right`}>Before</th>
                            <th scope="col" className={`${thClass} text-right`}>Recent</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((r) => (
                            <tr key={r.name}>
                              <th scope="row" className={`${tdClass} text-left font-normal`}>{r.name}</th>
                              <td className={`${tdClass} ${numClass} text-right`}>{formatBp(r.baseline_bp)}</td>
                              <td className={`${tdClass} ${numClass} text-right`}>{formatBp(r.recent_bp)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </Card>
              )}
            </>
          )}
          <p className="text-sm text-muted-foreground">
            Campaigns are still planned per location. To find the customers behind a brand, open the{" "}
            <Link to={SEGMENTS_PATH} className="underline underline-offset-2">
              segment view
            </Link>
            .
          </p>
        </div>
      )}
    </div>
  );
}
