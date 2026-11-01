import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RoiReport } from "../api/types";
import { ratioText, RoiView } from "./RoiPanel";

const base: RoiReport = {
  campaign_id: "c-1",
  status: "sent",
  verdict: "worked",
  window_over: true,
  arms: {
    treatment: { customers: 90, ordered: 30, orders: 40, revenue_paise: 900000 },
    holdout: { customers: 10, ordered: 2, orders: 2, revenue_paise: 40000 },
  },
  send_states: { pending: 0, submitted: 1, processing: 2, succeeded: 70, failed: 15, unknown: 2, skipped: 0 },
  incremental_revenue_paise: 540000,
  cost: { offer_budget_paise: 450000, message_cost_each_paise: 86, message_cost_paise: 6020, succeeded_sends: 70, gross_cost_paise: 456020, note: "Upper bound." },
  gross_margin_bp: 6000,
  gate: "ok",
  headline: { basis: "revenue", value_paise: 540000, net_paise: 83980, ratio_bp: 1841 },
  message: null,
  people_needed_per_arm: null,
  revenue_note: "Order-rate result is tested, revenue is indicative.",
  holdout_advice: { holdout_percent: 10, audience_n: 100, detectable_lift_bp: 2800, recommended_holdout_percent: 20, note: "" },
};

describe("RoiView", () => {
  it("shows the headline, all send states and the revenue caveat when the verdict allows it", () => {
    render(<RoiView roi={base} />);
    expect(screen.getByTestId("roi-headline")).toHaveTextContent("Revenue ROI");
    expect(screen.getByText(/15 failed/)).toBeInTheDocument();
    expect(screen.getByText(/2 unknown/)).toBeInTheDocument();
    expect(screen.getByText(/revenue is indicative/)).toBeInTheDocument();
    expect(screen.getByTestId("roi-holdout")).toHaveTextContent("20%");
  });

  it("never shows a result when the verdict is inconclusive", () => {
    render(
      <RoiView
        roi={{ ...base, verdict: "inconclusive", gate: "inconclusive", headline: null, incremental_revenue_paise: null, people_needed_per_arm: 1500 }}
      />,
    );
    expect(screen.getByText(/Not enough people to tell/)).toBeInTheDocument();
    expect(screen.getByText(/1500 people per group/)).toBeInTheDocument();
    expect(screen.queryByTestId("roi-headline")).not.toBeInTheDocument();
  });

  it("formats ratios with integer rounding", () => {
    expect(ratioText(1841)).toBe("18.4%");
    expect(ratioText(-2500)).toBe("-25.0%");
    expect(ratioText(null)).toBe("n/a");
  });
});
