// How each case stage (from the API) is displayed. The API decides the stage; this file only
// maps it to labels, colours and a position on the stepper.

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

export interface StageMeta {
  label: string;
  tone: Tone;
  /** One line for staff badges/filters; the customer text always comes from the API `message`. */
  hint: string;
}

export const STAGES: Record<string, StageMeta> = {
  received: { label: "Received", tone: "neutral", hint: "We have your report." },
  investigating: { label: "Investigating", tone: "accent", hint: "Checking the order facts." },
  awaiting_info: { label: "Waiting for your reply", tone: "warning", hint: "We asked a question." },
  awaiting_approval: { label: "Awaiting approval", tone: "accent", hint: "A person is reviewing the remedy." },
  processing: { label: "Processing", tone: "accent", hint: "The approved remedy is being carried out." },
  confirmed: { label: "Confirmed", tone: "success", hint: "The remedy is confirmed." },
  declined: { label: "Declined", tone: "danger", hint: "No remedy was approved." },
  escalated: { label: "With our team", tone: "info", hint: "A person is handling this." },
  closed: { label: "Closed", tone: "neutral", hint: "This case is closed." },
};

export const STAGE_ORDER = [
  "received",
  "investigating",
  "awaiting_info",
  "awaiting_approval",
  "processing",
  "confirmed",
  "declined",
  "escalated",
  "closed",
] as const;

export function stageMeta(stage: string): StageMeta {
  return STAGES[stage] ?? { label: stage.replace(/_/g, " "), tone: "neutral", hint: "" };
}

/** Stages during which the case is moving on its own, so the page polls. */
export function isActiveStage(stage: string): boolean {
  return stage === "investigating" || stage === "processing";
}

export type StepState = "done" | "current" | "upcoming" | "skipped";

export interface Step {
  key: string;
  label: string;
  state: StepState;
  tone: Tone;
}

const HAPPY = [
  { key: "received", label: "Received" },
  { key: "investigating", label: "Investigating" },
  { key: "awaiting_approval", label: "Awaiting approval" },
  { key: "processing", label: "Processing" },
  { key: "confirmed", label: "Confirmed" },
];

/**
 * Where each off-path stage sits on the five-step stepper, and what replaces that step.
 * awaiting_info pauses investigation; declined ends at the approval step; escalated hands
 * over after investigation; closed is shown as a finished case.
 */
const OFF_PATH: Record<string, { at: number; label: string; tone: Tone; terminal: boolean }> = {
  awaiting_info: { at: 1, label: "Waiting for your reply", tone: "warning", terminal: false },
  escalated: { at: 2, label: "With our team", tone: "info", terminal: false },
  declined: { at: 2, label: "Declined", tone: "danger", terminal: true },
};

export function stepperModel(stage: string): Step[] {
  if (stage === "closed") {
    return [
      ...HAPPY.slice(0, 1).map((s) => ({ ...s, state: "done" as const, tone: "neutral" as Tone })),
      { key: "closed", label: "Closed", state: "current", tone: "neutral" },
    ];
  }
  const off = OFF_PATH[stage];
  if (off) {
    return HAPPY.map((s, i): Step => {
      if (i < off.at) return { ...s, state: "done", tone: "success" };
      if (i === off.at) return { key: stage, label: off.label, state: "current", tone: off.tone };
      return { ...s, state: off.terminal ? "skipped" : "upcoming", tone: "neutral" };
    });
  }
  const idx = HAPPY.findIndex((s) => s.key === stage);
  const current = idx === -1 ? 0 : idx;
  return HAPPY.map((s, i): Step => {
    if (stage === "confirmed" && i === current) return { ...s, state: "done", tone: "success" };
    if (i < current) return { ...s, state: "done", tone: "success" };
    if (i === current) return { ...s, state: "current", tone: "accent" };
    return { ...s, state: "upcoming", tone: "neutral" };
  });
}
