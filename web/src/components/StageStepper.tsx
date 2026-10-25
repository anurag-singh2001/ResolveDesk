import { stepperModel } from "../lib/stages";
import type { Step, Tone } from "../lib/stages";
import { cx } from "./ui";

const DOT: Record<Tone, string> = {
  neutral: "bg-slate-500 ring-slate-200",
  accent: "bg-accent-600 ring-accent-100",
  success: "bg-emerald-600 ring-emerald-100",
  warning: "bg-amber-500 ring-amber-100",
  danger: "bg-rose-600 ring-rose-100",
  info: "bg-sky-600 ring-sky-100",
};

function Marker({ step, index }: { step: Step; index: number }) {
  if (step.state === "done") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-600 text-white" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" />
        </svg>
      </span>
    );
  }
  if (step.state === "current") {
    return (
      <span className={cx("flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold text-white ring-4", DOT[step.tone])} aria-hidden="true">
        {index + 1}
      </span>
    );
  }
  return (
    <span
      className={cx(
        "flex h-7 w-7 items-center justify-center rounded-full border-2 bg-white text-xs font-medium",
        step.state === "skipped" ? "border-dashed border-slate-200 text-slate-300" : "border-slate-300 text-slate-400",
      )}
      aria-hidden="true"
    >
      {index + 1}
    </span>
  );
}

const STATE_TEXT: Record<Step["state"], string> = {
  done: "completed",
  current: "current step",
  upcoming: "not started",
  skipped: "skipped",
};

export function StageStepper({ stage }: { stage: string }) {
  const steps = stepperModel(stage);
  return (
    <nav aria-label="Case progress">
      <ol className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-0" data-stage={stage}>
        {steps.map((step, i) => (
          <li
            key={step.key}
            data-state={step.state}
            data-step={step.key}
            aria-current={step.state === "current" ? "step" : undefined}
            className="relative flex items-center gap-3 sm:flex-1 sm:flex-col sm:items-center sm:gap-2 sm:text-center"
          >
            {i < steps.length - 1 && (
              <span
                aria-hidden="true"
                className={cx(
                  "absolute hidden h-0.5 sm:left-[calc(50%+1.25rem)] sm:right-[calc(-50%+1.25rem)] sm:top-3.5 sm:block",
                  steps[i + 1].state === "done" || steps[i + 1].state === "current" ? "bg-emerald-500" : "bg-slate-200",
                )}
              />
            )}
            <Marker step={step} index={i} />
            <span
              className={cx(
                "text-sm",
                step.state === "current" ? "font-semibold text-slate-900" : step.state === "done" ? "text-slate-700" : "text-slate-400",
                step.state === "skipped" && "line-through",
              )}
            >
              {step.label}
              <span className="sr-only"> ({STATE_TEXT[step.state]})</span>
            </span>
          </li>
        ))}
      </ol>
    </nav>
  );
}
