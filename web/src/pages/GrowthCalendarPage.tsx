import { api } from "../api/endpoints";
import type { CalendarCampaign } from "../api/types";
import { Alert, Badge, Card, EmptyState, ErrorState, Loading, PageHeader, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "purple" | "muted";

// One colour per campaign status. The send words below are separate and are never merged.
const STATUS_TONE: Record<string, Tone> = {
  pending_approval: "warning",
  approved: "info",
  executing: "info",
  sent: "success",
  measured: "purple",
  rejected: "danger",
  expired: "muted",
};
const STATUS_BAR: Record<string, string> = {
  pending_approval: "bg-yellow-600/70 dark:bg-yellow-400/70",
  approved: "bg-sky-600/70 dark:bg-sky-400/70",
  executing: "bg-sky-600/70 dark:bg-sky-400/70",
  sent: "bg-green-600/70 dark:bg-green-400/70",
  measured: "bg-purple-600/70 dark:bg-purple-400/70",
  rejected: "bg-red-600/70 dark:bg-red-400/70",
  expired: "bg-muted-foreground/50",
};
const LEGEND = ["pending_approval", "approved", "sent", "measured", "rejected", "expired"];
// Every send state, in the order a send moves through them. "sent" is not one of them.
const SEND_ORDER = ["pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped"];

const dayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const day = (iso: string) => dayFmt.format(new Date(iso));

/** Whole-percent position of a time inside the visible range (display only). */
function pctOf(t: number, lo: number, hi: number): number {
  return hi <= lo ? 0 : Math.round(((t - lo) * 100) / (hi - lo));
}

export function sendWords(c: CalendarCampaign): string {
  const parts = SEND_ORDER.filter((k) => (c.send_counts[k] ?? 0) > 0).map((k) => `${c.send_counts[k]} ${k}`);
  return parts.length ? parts.join(" · ") : "none";
}

function Bar({ c, lo, hi }: { c: CalendarCampaign; lo: number; hi: number }) {
  const left = pctOf(new Date(c.start).getTime(), lo, hi);
  const right = pctOf(new Date(c.window_end).getTime(), lo, hi);
  return (
    <div className="relative h-3 w-full min-w-40 rounded bg-border/40" role="img" aria-label={`${humanize(c.status)}, ${day(c.start)} to ${day(c.window_end)}`}>
      <div className={`absolute top-0 h-3 rounded ${STATUS_BAR[c.status] ?? "bg-muted-foreground/50"}`} style={{ left: `${left}%`, width: `${Math.max(right - left, 2)}%` }} />
    </div>
  );
}

export function GrowthCalendarPage() {
  const { data, error, loading, reload } = useApi(() => api.growthCalendar(), []);

  return (
    <div>
      <PageHeader
        title="Campaign calendar"
        subtitle="Win-back campaigns in your scope across their measurement windows. Read-only: approve or reject on the Growth page."
      />
      {loading ? (
        <Loading label="Loading calendar…" />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data.campaigns.length === 0 ? (
        <EmptyState title="No campaigns yet">Campaigns show here once a signal has been turned into a proposal.</EmptyState>
      ) : (
        <CalendarBody campaigns={data.campaigns} />
      )}
    </div>
  );
}

function CalendarBody({ campaigns }: { campaigns: CalendarCampaign[] }) {
  const lo = Math.min(...campaigns.map((c) => new Date(c.start).getTime()));
  const hi = Math.max(...campaigns.map((c) => new Date(c.window_end).getTime()));
  const overlap = campaigns.reduce((n, c) => n + c.overlap_customers, 0);
  const capped = campaigns.reduce((n, c) => n + c.frequency_cap_customers, 0);
  return (
    <div className="space-y-4">
      {(overlap > 0 || capped > 0) && (
        <Alert tone="warning">
          Heads up, nothing is blocked: {overlap} customer{overlap === 1 ? "" : "s"} in overlapping campaigns and {capped} inside the 30-day frequency cap. The cap itself is enforced when the audience is built and again at send time.
        </Alert>
      )}
      <ul className="flex flex-wrap gap-2 text-xs" aria-label="Status colours">
        {LEGEND.map((s) => (
          <li key={s}>
            <Badge tone={STATUS_TONE[s]}>{humanize(s)}</Badge>
          </li>
        ))}
      </ul>
      <Card>
        <div className={tableWrapClass}>
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={thClass}>Campaign</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Window</th>
                <th className={thClass}>Audience</th>
                <th className={thClass}>Budget</th>
                <th className={thClass}>Sends</th>
                <th className={thClass}>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id} data-testid="calendar-row">
                  <td className={tdClass}>
                    <div className="font-medium">{c.location_name}</div>
                    <div className="text-xs text-muted-foreground">{c.brands.map((b) => b.name).join(", ") || "No brand"}</div>
                  </td>
                  <td className={tdClass}>
                    <Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{humanize(c.status)}</Badge>
                  </td>
                  <td className={tdClass}>
                    <Bar c={c} lo={lo} hi={hi} />
                    <div className="mt-1 text-xs text-muted-foreground">
                      {day(c.start)} to {day(c.window_end)} ({c.window_days} days)
                    </div>
                  </td>
                  <td className={tdClass}>
                    {c.audience_n} <span className="text-xs text-muted-foreground">({c.treatment_n} treated, {c.holdout_n} held out)</span>
                  </td>
                  <td className={tdClass}>{formatPaise(c.budget_paise)}</td>
                  <td className={tdClass}>{sendWords(c)}</td>
                  <td className={tdClass}>
                    <div>{c.overlap_customers} in overlapping campaigns</div>
                    <div>{c.frequency_cap_customers} inside the frequency cap</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
