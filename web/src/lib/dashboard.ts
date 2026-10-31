import type { MetricPoint, MetricsResponse } from "../api/types";

export const NO_DATA = "No data";

/** Basis points → "12.50%" with integer maths. Null means no data, never 0%. */
export function formatBp(bp: number | null | undefined): string {
  if (bp === null || bp === undefined) return NO_DATA;
  const b = Math.trunc(bp);
  return `${Math.floor(b / 100)}.${String(b % 100).padStart(2, "0")}%`;
}

export function formatBpShort(bp: number): string {
  return `${Math.floor(bp / 100)}%`;
}

export function formatMinutes(m: number | null | undefined): string {
  return m === null || m === undefined ? NO_DATA : `${m} min`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-09" → "9 Mar", read from the string so no timezone shifts the day. */
export function bucketLabel(iso: string, granularity: "day" | "week"): string {
  const [, m, d] = iso.split("-").map(Number);
  const text = `${d} ${MONTHS[(m ?? 1) - 1]}`;
  return granularity === "week" ? `Week of ${text}` : text;
}

const TZ_ABBR: Record<string, string> = { "Asia/Kolkata": "IST" };

/** Timezone as the response names it, with a short form where known: "Asia/Kolkata (IST)". */
export function timezoneLabel(tz: string): string {
  const abbr = TZ_ABBR[tz];
  return abbr ? `${tz} (${abbr})` : tz;
}

/** True when any bucket holds any activity at all. */
export function hasActivity(res: MetricsResponse | undefined): boolean {
  return !!res?.groups.some((g) =>
    g.points.some((p) => p.cases_opened > 0 || p.orders > 0 || p.decisions > 0 || p.remedy_spend_paise > 0),
  );
}

export interface GroupTotals {
  cases: number;
  remedyPaise: number;
  orders: number;
  revenuePaise: number;
}

/** Sums of integer counters over the period; rates are not summed, they come per bucket. */
export function totalsOf(points: MetricPoint[]): GroupTotals {
  return points.reduce<GroupTotals>(
    (t, p) => ({
      cases: t.cases + p.cases_opened,
      remedyPaise: t.remedyPaise + p.remedy_spend_paise,
      orders: t.orders + p.orders,
      revenuePaise: t.revenuePaise + p.revenue_paise,
    }),
    { cases: 0, remedyPaise: 0, orders: 0, revenuePaise: 0 },
  );
}
