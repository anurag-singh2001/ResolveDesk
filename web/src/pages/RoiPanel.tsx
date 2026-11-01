import { api } from "../api/endpoints";
import type { RoiReport } from "../api/types";
import { Alert, Dl } from "../components/ui";
import { humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

// The send states beside the result, each kept apart (never folded into "sent").
const SEND_ORDER = ["pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped"];

/** Basis points as a percent, integer rounding half away from zero (display only). */
export function ratioText(bp: number | null): string {
  if (bp === null) return "n/a";
  const tenths = Math.floor((Math.abs(bp) + 5) / 10);
  return `${bp < 0 ? "-" : ""}${Math.floor(tenths / 10)}.${tenths % 10}%`;
}

export function RoiView({ roi }: { roi: RoiReport }) {
  const t = roi.arms.treatment;
  const h = roi.arms.holdout;
  const adv = roi.holdout_advice;
  return (
    <div className="card-chai space-y-2 p-3 text-sm" data-testid="roi">
      <div className="font-medium text-foreground">Return on the offer</div>
      {roi.headline ? (
        <div data-testid="roi-headline">
          <div className="text-foreground">
            {humanize(roi.headline.basis)} ROI: {formatPaise(roi.headline.net_paise)} ({ratioText(roi.headline.ratio_bp)} of cost)
          </div>
          <p className="text-xs text-muted-foreground">
            {roi.headline.basis === "margin"
              ? `Margin ROI at an estimated ${ratioText(roi.gross_margin_bp)} gross margin.`
              : "Revenue ROI: incremental revenue minus cost, margin not assumed."}{" "}
            Incremental revenue {formatPaise(roi.incremental_revenue_paise)}.
          </p>
        </div>
      ) : roi.gate === "inconclusive" ? (
        <Alert tone="warning">
          Not enough people to tell. About {roi.people_needed_per_arm} people per group would be needed to see a 5-point lift.
        </Alert>
      ) : (
        <Alert tone="info">The measurement window is still open, so there is no result yet.</Alert>
      )}
      <Dl
        items={[
          ["Offered group", `${t.customers} people, ${t.ordered} ordered, ${t.orders} orders, ${formatPaise(t.revenue_paise)}`],
          ["Held-out group", `${h.customers} people, ${h.ordered} ordered, ${h.orders} orders, ${formatPaise(h.revenue_paise)}`],
          ["Send states (offered group)", SEND_ORDER.map((k) => `${roi.send_states[k] ?? 0} ${k}`).join(" · ")],
          ["Cost, upper bound", formatPaise(roi.cost.gross_cost_paise)],
        ]}
      />
      <p className="text-xs text-muted-foreground">
        {roi.cost.note} Message cost {formatPaise(roi.cost.message_cost_each_paise)} each (estimate). Failed and unknown sends
        stay in the offered group. {roi.revenue_note}
      </p>
      <p className="text-xs text-muted-foreground" data-testid="roi-holdout">
        Holdout {adv.holdout_percent}%: this split can reliably see a lift of about{" "}
        {adv.detectable_lift_bp === null ? "n/a" : ratioText(adv.detectable_lift_bp)} points (estimate).
        {adv.recommended_holdout_percent !== null &&
          ` For an audience this small, ${adv.recommended_holdout_percent}% is worth considering.`}
      </p>
    </div>
  );
}

export function RoiPanel({ campaignId }: { campaignId: string }) {
  const { data } = useApi(() => api.campaignRoi(campaignId), [campaignId]);
  if (!data) return null; // a failed read adds nothing; the campaign panel still works
  return <RoiView roi={data} />;
}
