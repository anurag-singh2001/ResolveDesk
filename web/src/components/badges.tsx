import { stageMeta } from "../lib/stages";
import type { Tone } from "../lib/stages";
import { humanize } from "../lib/format";
import { Badge } from "./ui";

// Stage to status colour: green confirmed, red failed, yellow needs a person,
// purple waiting for approval, neutral processing (with a live dot), muted declined/closed.
const STAGE_TONE: Record<string, "success" | "danger" | "warning" | "purple" | "live" | "muted" | "neutral"> = {
  received: "neutral",
  investigating: "neutral",
  awaiting_info: "warning",
  awaiting_approval: "purple",
  processing: "live",
  confirmed: "success",
  declined: "muted",
  escalated: "warning",
  closed: "muted",
};

export function StageBadge({ stage }: { stage: string }) {
  const m = stageMeta(stage);
  return <Badge tone={STAGE_TONE[stage] ?? "neutral"}>{m.label}</Badge>;
}

const RISK_TONE: Record<string, Tone> = { low: "success", medium: "warning", high: "danger" };

export function RiskBadge({ risk }: { risk: string }) {
  return <Badge tone={RISK_TONE[risk] ?? "neutral"}>{humanize(risk)} risk</Badge>;
}

export function OrderStatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "delivered" || status === "completed"
      ? "success"
      : status === "cancelled" || status === "failed"
        ? "danger"
        : "neutral";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}
