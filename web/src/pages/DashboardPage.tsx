import { useSearchParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/endpoints";
import type { MetricGroup, MetricPoint, MetricsResponse } from "../api/types";
import { Card, EmptyState, ErrorState, Loading, PageHeader, cx, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { NO_DATA, bucketLabel, formatBp, formatBpShort, formatMinutes, hasActivity, timezoneLabel, totalsOf } from "../lib/dashboard";
import { formatPaise, formatPaiseShort } from "../lib/money";
import { useApi } from "../lib/useApi";

const PERIODS = [7, 14, 30, 90, 180, 366];

type Row = Record<string, number | string | null>;

interface SeriesDef {
  key: string;
  label: string;
  color: string; // CSS variable, stepped for dark mode in index.css
}

interface ChartDef {
  id: string;
  title: string;
  hint?: string;
  kind: "bar" | "stack" | "line";
  series: SeriesDef[];
  format: (v: number | null) => string;
  tick: (v: number) => string;
  domain?: [number, number];
  reference?: { y: number; label: string };
}

const S1 = "var(--viz-1)";
const S2 = "var(--viz-2)";

function chartsFor(res: MetricsResponse): ChartDef[] {
  const plain = (n: number | null) => (n === null ? NO_DATA : String(n));
  const sla = res.decision_sla_minutes;
  return [
    { id: "cases", title: "Cases opened", kind: "bar", series: [{ key: "cases_opened", label: "Cases opened", color: S1 }], format: plain, tick: String },
    {
      id: "remedy",
      title: "Remedy spend",
      hint: "Refunds and vouchers, by when they succeeded.",
      kind: "stack",
      series: [
        { key: "refunds_paise", label: "Refunds", color: S1 },
        { key: "vouchers_paise", label: "Vouchers", color: S2 },
      ],
      format: formatPaise,
      tick: formatPaiseShort,
    },
    {
      id: "decision",
      title: "Median decision time",
      hint: "Minutes from proposal to a person's decision.",
      kind: "line",
      series: [{ key: "median_decision_minutes", label: "Median decision time", color: S1 }],
      format: formatMinutes,
      tick: String,
      reference: { y: sla, label: `SLA ${sla} min` },
    },
    {
      id: "sla",
      title: "Decisions within SLA",
      hint: `Share decided within ${sla} minutes.`,
      kind: "line",
      series: [{ key: "sla_met_bp", label: "Within SLA", color: S1 }],
      format: formatBp,
      tick: formatBpShort,
      domain: [0, 10000],
    },
    {
      id: "repeat",
      title: "Repeat rate",
      hint: "Share of orders that were repeats.",
      kind: "line",
      series: [{ key: "repeat_rate_bp", label: "Repeat rate", color: S1 }],
      format: formatBp,
      tick: formatBpShort,
      domain: [0, 10000],
    },
    {
      id: "ai",
      title: "AI accuracy",
      hint: "Share of AI proposals staff did not override.",
      kind: "line",
      series: [{ key: "ai_accuracy_bp", label: "AI accuracy", color: S1 }],
      format: formatBp,
      tick: formatBpShort,
      domain: [0, 10000],
    },
    { id: "orders", title: "Orders", kind: "bar", series: [{ key: "orders", label: "Orders", color: S1 }], format: plain, tick: String },
    { id: "aov", title: "Average order value", kind: "line", series: [{ key: "aov_paise", label: "Average order value", color: S1 }], format: formatPaise, tick: formatPaiseShort },
  ];
}

function rowsOf(points: MetricPoint[], granularity: "day" | "week"): Row[] {
  return points.map((p) => ({ ...(p as unknown as Row), label: bucketLabel(p.bucket_start, granularity) }));
}

function ChartCard({ def, rows }: { def: ChartDef; rows: Row[] }) {
  const axis = { fill: "var(--muted-foreground)", fontSize: 11 };
  const common = { data: rows, margin: { top: 8, right: 8, bottom: 0, left: 0 } };
  const parts = [
    <CartesianGrid key="g" stroke="var(--border)" vertical={false} />,
    <XAxis key="x" dataKey="label" tick={axis} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={24} />,
    <YAxis key="y" tick={axis} tickLine={false} axisLine={false} width={64} tickFormatter={def.tick} domain={def.domain ?? [0, "auto"]} />,
    <Tooltip
      key="t"
      cursor={{ stroke: "var(--border)" }}
      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--foreground)", fontSize: 12 }}
      formatter={(v: unknown, name: string) => [def.format(typeof v === "number" ? v : null), name]}
    />,
    def.series.length > 1 ? <Legend key="l" /> : null,
  ];
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-foreground">{def.title}</h2>
      {def.hint && <p className="mt-0.5 text-xs text-muted-foreground">{def.hint}</p>}
      <div className="mt-3 h-56 w-full" data-testid={`chart-${def.id}`}>
        <ResponsiveContainer width="100%" height="100%">
          {def.kind === "line" ? (
            <LineChart {...common}>
              {parts}
              {def.reference && (
                <ReferenceLine
                  y={def.reference.y}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="4 4"
                  label={{ value: def.reference.label, fill: "var(--muted-foreground)", fontSize: 11, position: "insideTopRight" }}
                />
              )}
              {def.series.map((s) => (
                // connectNulls stays false: a null bucket is a gap, not a zero.
                <Line
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={{ r: 4, stroke: "var(--card)", strokeWidth: 2, fill: s.color }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart {...common}>
              {parts}
              {def.series.map((s) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  fill={s.color}
                  stackId={def.kind === "stack" ? "a" : undefined}
                  stroke="var(--card)"
                  strokeWidth={def.kind === "stack" ? 2 : 0}
                  radius={def.kind === "stack" ? 0 : [4, 4, 0, 0]}
                  maxBarSize={28}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-xs" data-testid={`table-${def.id}`}>
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Table view</summary>
        <div className={cx(tableWrapClass, "mt-2 max-h-64 overflow-y-auto")}>
          <table className={tableClass}>
            <caption className="sr-only">{def.title} by period</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Period</th>
                {def.series.map((s) => (
                  <th key={s.key} scope="col" className={`${thClass} text-right`}>{s.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.bucket_start)}>
                  <th scope="row" className={`${tdClass} text-left font-normal`}>{String(r.label)}</th>
                  {def.series.map((s) => {
                    const v = r[s.key];
                    return <td key={s.key} className={`${tdClass} ${numClass} text-right`}>{def.format(typeof v === "number" ? v : null)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; text: string }[]; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx("h-8 rounded px-3 text-sm font-medium transition-colors", o.value === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
        >
          {o.text}
        </button>
      ))}
    </div>
  );
}

/** Drill-down table: one row per brand or location with period totals; the name drills in. */
function BreakdownTable({ title, groups, onPick }: { title: string; groups: MetricGroup[]; onPick: (g: MetricGroup) => void }) {
  return (
    <section aria-label={title}>
      <h2 className="mb-2 text-sm font-semibold text-foreground">{title}</h2>
      <div className={tableWrapClass}>
        <table className={tableClass}>
          <caption className="sr-only">{title}, totals for the period</caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>Name</th>
              <th scope="col" className={`${thClass} text-right`}>Cases</th>
              <th scope="col" className={`${thClass} text-right`}>Remedy spend</th>
              <th scope="col" className={`${thClass} text-right`}>Orders</th>
              <th scope="col" className={`${thClass} text-right`}>Revenue</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const t = totalsOf(g.points);
              return (
                <tr key={g.id ?? g.name} className="hover:bg-muted">
                  <th scope="row" className={`${tdClass} text-left font-medium`}>
                    {g.id && groups.length > 1 ? (
                      <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => onPick(g)}>
                        {g.name}
                      </button>
                    ) : (
                      g.name
                    )}
                  </th>
                  <td className={`${tdClass} ${numClass} text-right`}>{t.cases}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(t.remedyPaise)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{t.orders}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(t.revenuePaise)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const granularity = params.get("g") === "week" ? "week" : "day";
  const requested = Number(params.get("days"));
  const days = PERIODS.includes(requested) ? requested : 30;
  // Ids go to the server, which can only narrow its own scope by them. Names are display only.
  const brandId = params.get("brand") ?? undefined;
  const locationId = params.get("location") ?? undefined;
  const brandName = params.get("bname") ?? "Brand";
  const locationName = params.get("lname") ?? "Location";

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next);
  };

  const deps = [granularity, days, brandId, locationId];
  const q = { granularity, days, location_id: locationId, brand_id: brandId } as const;
  const main = useApi(() => api.metrics({ ...q, group_by: "none" }), deps);
  const byLocation = useApi(() => (locationId ? Promise.resolve(undefined) : api.metrics({ ...q, group_by: "location" })), deps);
  const byBrand = useApi(() => (locationId || brandId ? Promise.resolve(undefined) : api.metrics({ ...q, group_by: "brand" })), deps);

  const res = main.data;
  const series = res?.groups[0]?.points ?? [];
  const drilled = Boolean(brandId || locationId);

  return (
    <div className="viz-root">
      <PageHeader
        title="Dashboard"
        subtitle="Cases, remedies, decisions and orders for the locations in your scope. Read-only."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Granularity" value={granularity} options={[{ value: "day", text: "Day" }, { value: "week", text: "Week" }]} onChange={(v) => set({ g: v === "day" ? null : v })} />
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Period</span>
              <select
                aria-label="Period"
                value={days}
                onChange={(e) => set({ days: e.target.value === "30" ? null : e.target.value })}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
              >
                {PERIODS.map((d) => (
                  <option key={d} value={d}>Last {d} days</option>
                ))}
              </select>
            </label>
          </div>
        }
      />
      <div className="mb-4 space-y-1">
        <nav aria-label="Drill-down" className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
          {drilled ? (
            <button type="button" className="hover:text-foreground hover:underline" onClick={() => set({ brand: null, bname: null, location: null, lname: null })}>
              All in scope
            </button>
          ) : (
            <span className="text-foreground">All in scope</span>
          )}
          {brandId && (
            <>
              <span aria-hidden="true">/</span>
              {locationId ? (
                <button type="button" className="hover:text-foreground hover:underline" onClick={() => set({ location: null, lname: null })}>{brandName}</button>
              ) : (
                <span className="text-foreground">{brandName}</span>
              )}
            </>
          )}
          {locationId && (
            <>
              <span aria-hidden="true">/</span>
              <span className="text-foreground">{locationName}</span>
            </>
          )}
        </nav>
        {res && (
          <p className="text-xs text-muted-foreground" data-testid="dashboard-meta">
            {res.start} to {res.end} · Times in {timezoneLabel(res.timezone)} · Decision SLA {res.decision_sla_minutes} min
          </p>
        )}
      </div>

      {main.loading ? (
        <Loading label="Loading dashboard…" />
      ) : main.error ? (
        <ErrorState error={main.error} onRetry={main.reload} />
      ) : !res || !hasActivity(res) ? (
        <EmptyState title="No activity in this period">Try a longer period, or another location.</EmptyState>
      ) : (
        <div className="space-y-6">
          {byBrand.data && byBrand.data.groups.length > 0 && (
            <BreakdownTable title="By brand" groups={byBrand.data.groups} onPick={(g) => g.id && set({ brand: g.id, bname: g.name, location: null, lname: null })} />
          )}
          {byLocation.data && byLocation.data.groups.length > 0 && (
            <BreakdownTable title="By location" groups={byLocation.data.groups} onPick={(g) => g.id && set({ location: g.id, lname: g.name })} />
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            {chartsFor(res).map((def) => (
              <ChartCard key={def.id} def={def} rows={rowsOf(series, res.granularity)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
