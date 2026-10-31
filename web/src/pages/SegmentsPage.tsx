import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/endpoints";
import type { CohortGroup, SegmentCell, SegmentGroup } from "../api/types";
import { Card, EmptyState, ErrorState, Loading, PageHeader, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { NO_DATA, formatBp } from "../lib/dashboard";
import { formatPaise, formatPaiseShort } from "../lib/money";
import { useApi } from "../lib/useApi";

const LABEL: Record<string, string> = {
  new: "New",
  active: "Active",
  loyal: "Loyal",
  at_risk: "At risk",
  lapsed: "Lapsed",
  lapsed_regular: "Lapsed regulars",
  one_and_done: "One-and-done",
};

const HELP: Record<string, string> = {
  new: "First order within the new-customer window.",
  active: "Ordered within the lapsed window.",
  loyal: "Active, and in the top group on both orders and spend.",
  at_risk: "Active, but quiet for more than twice their usual gap between orders.",
  lapsed: "No order since the lapsed cut-off.",
  lapsed_regular: "Lapsed, but were loyal by their history.",
  one_and_done: "Exactly one order, and not a new customer.",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthLabel(iso: string): string {
  const [y, m] = iso.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

const num = (v: number | null) => (v === null ? "Hidden" : String(v));

function SegmentTable({ group, minimum }: { group: SegmentGroup; minimum: number }) {
  return (
    <div className={tableWrapClass}>
      <table className={tableClass} data-testid="segments-table">
        <caption className="sr-only">Segments for {group.name}</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>Segment</th>
            <th scope="col" className={`${thClass} text-right`}>Customers</th>
            <th scope="col" className={`${thClass} text-right`}>Share of base</th>
            <th scope="col" className={`${thClass} text-right`}>Average order</th>
            <th scope="col" className={`${thClass} text-right`}>Total spend</th>
            <th scope="col" className={`${thClass} text-right`}>Can be messaged on WhatsApp</th>
            <th scope="col" className={`${thClass} text-right`}>Own channel</th>
            <th scope="col" className={`${thClass} text-right`}>Delivery app only</th>
            <th scope="col" className={`${thClass} text-right`}>Delivery app only, not contactable</th>
          </tr>
        </thead>
        <tbody>
          {group.segments.map((c: SegmentCell) => (
            <tr key={c.segment}>
              <th scope="row" className={`${tdClass} text-left font-medium`} title={HELP[c.segment]}>
                {LABEL[c.segment] ?? c.segment}
              </th>
              {c.suppressed ? (
                <td colSpan={8} className={`${tdClass} text-muted-foreground`}>
                  Hidden: fewer than {minimum} customers
                </td>
              ) : (
                <>
                  <td className={`${tdClass} ${numClass} text-right`}>{num(c.in_segment)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatBp(c.share_bp)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{c.aov_paise === null ? NO_DATA : formatPaise(c.aov_paise)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(c.total_spend_paise)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{num(c.contactable_whatsapp)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{num(c.own_channel)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{num(c.aggregator_only)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{num(c.aggregator_only_not_contactable)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SegmentChart({ group }: { group: SegmentGroup }) {
  const axis = { fill: "var(--muted-foreground)", fontSize: 11 };
  // A hidden segment is left out of the chart, not drawn as zero.
  const rows = group.segments
    .filter((c) => !c.suppressed)
    .map((c) => ({ label: LABEL[c.segment] ?? c.segment, in_segment: c.in_segment, contactable: c.contactable_whatsapp }));
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-foreground">Customers by segment</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Segments overlap, so the bars do not add up to the customer total. The second bar is who you may message on WhatsApp.
      </p>
      <div className="mt-3 h-64 w-full" data-testid="chart-segments">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={{ stroke: "var(--border)" }} interval={0} />
            <YAxis tick={axis} tickLine={false} axisLine={false} width={48} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--foreground)", fontSize: 12 }}
            />
            <Legend />
            <Bar dataKey="in_segment" name="Customers" fill="var(--viz-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            <Bar dataKey="contactable" name="Can be messaged on WhatsApp" fill="var(--viz-2)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Total spend per segment: {group.segments.filter((c) => !c.suppressed).map((c) => `${LABEL[c.segment]} ${formatPaiseShort(c.total_spend_paise)}`).join(" · ")}</p>
    </Card>
  );
}

function CohortTable({ group, minimum }: { group: CohortGroup; minimum: number }) {
  return (
    <div className={tableWrapClass}>
      <table className={tableClass} data-testid="cohort-table">
        <caption className="sr-only">First-order cohorts for {group.name}</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>First order</th>
            <th scope="col" className={`${thClass} text-right`}>Customers</th>
            <th scope="col" className={`${thClass} text-right`}>Ordered again, month 1</th>
            <th scope="col" className={`${thClass} text-right`}>Month 2</th>
            <th scope="col" className={`${thClass} text-right`}>Month 3</th>
          </tr>
        </thead>
        <tbody>
          {group.cohorts.map((r) => (
            <tr key={r.cohort_month}>
              <th scope="row" className={`${tdClass} text-left font-medium`}>{monthLabel(r.cohort_month)}</th>
              {r.suppressed ? (
                <td colSpan={4} className={`${tdClass} text-muted-foreground`}>
                  Hidden: fewer than {minimum} customers
                </td>
              ) : (
                <>
                  <td className={`${tdClass} ${numClass} text-right`}>{r.size}</td>
                  {r.cells.map((c) => (
                    <td key={c.month} className={`${tdClass} ${numClass} text-right`}>
                      {!c.measurable ? "Not yet" : c.return_bp === null ? NO_DATA : `${formatBp(c.return_bp)} (${c.returned})`}
                    </td>
                  ))}
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SegmentsPage() {
  const segs = useApi(() => api.segments(), []);
  const cohorts = useApi(() => api.cohorts(), []);
  const [pick, setPick] = useState<string>("all");

  const res = segs.data;
  const group = res?.groups.find((g) => (g.id ?? "all") === pick) ?? res?.groups[0];
  const cohortGroup = cohorts.data?.groups.find((g) => (g.id ?? "all") === (group?.id ?? "all"));

  return (
    <div className="viz-root">
      <PageHeader
        title="Segments"
        subtitle="Who your customers are, by how they order. Counts only; no names or numbers. Read-only."
        actions={
          res && res.groups.length > 1 ? (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Brand</span>
              <select
                aria-label="Brand"
                value={group?.id ?? "all"}
                onChange={(e) => setPick(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
              >
                {res.groups.map((g) => (
                  <option key={g.id ?? "all"} value={g.id ?? "all"}>{g.name}</option>
                ))}
              </select>
            </label>
          ) : undefined
        }
      />
      {segs.loading ? (
        <Loading label="Loading segments…" />
      ) : segs.error ? (
        <ErrorState error={segs.error} onRetry={segs.reload} />
      ) : !res || !group || group.customers === 0 ? (
        <EmptyState title="No customers with orders yet">Segments appear once customers have placed orders in your scope.</EmptyState>
      ) : (
        <div className="space-y-6">
          <p className="text-xs text-muted-foreground" data-testid="segments-meta">
            {group.customers} customers with orders · lapsed means no order for {res.lapsed_days} days · new means first order in the last {res.new_days} days.
            Counts include customers who have not agreed to marketing; only the WhatsApp column reflects consent.
            {res.cells_hidden_below_min && ` Groups under ${res.small_cell_min} customers are hidden.`}
          </p>
          <SegmentChart group={group} />
          <section aria-label="Segment table">
            <h2 className="mb-2 text-sm font-semibold text-foreground">Segment detail</h2>
            <SegmentTable group={group} minimum={res.small_cell_min} />
          </section>
          <section aria-label="Cohorts">
            <h2 className="mb-1 text-sm font-semibold text-foreground">First-order cohorts</h2>
            <p className="mb-2 text-xs text-muted-foreground">Share of each month's new customers who ordered again 1, 2 and 3 months later. "Not yet" means that month is not over.</p>
            {cohorts.loading ? (
              <Loading label="Loading cohorts…" />
            ) : cohorts.error ? (
              <ErrorState error={cohorts.error} onRetry={cohorts.reload} />
            ) : cohortGroup ? (
              <CohortTable group={cohortGroup} minimum={res.small_cell_min} />
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
