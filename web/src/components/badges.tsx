import { stageMeta } from "../lib/stages";
import type { Tone } from "../lib/stages";
import { humanize } from "../lib/format";
import { Badge } from "./ui";

export function StageBadge({ stage }: { stage: string }) {
  const m = stageMeta(stage);
  return <Badge tone={m.tone}>{m.label}</Badge>;
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
