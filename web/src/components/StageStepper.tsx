import { stepperModel } from "../lib/stages";
import type { Step, Tone } from "../lib/stages";
import { cx } from "./ui";

// Neutral stepper: the current step is ink/white, done steps are muted, warning states are yellow text.
const CURRENT: Record<Tone, string> = {
  neutral: "bg-neutral-900 text-white dark:bg-white dark:text-black",
  accent: "bg-neutral-900 text-white dark:bg-white dark:text-black",
  success: "bg-neutral-900 text-white dark:bg-white dark:text-black",
  warning: "border border-yellow-600/60 text-yellow-700 dark:border-yellow-400/60 dark:text-yellow-400",
  info: "border border-yellow-600/60 text-yellow-700 dark:border-yellow-400/60 dark:text-yellow-400",
  danger: "border border-border text-muted-foreground",
};

const LABEL_WARN = "text-yellow-700 dark:text-yellow-400";

function Marker({ step, index }: { step: Step; index: number }) {
  if (step.state === "done") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border text-muted-foreground" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" />
        </svg>
      </span>
    );
  }
  if (step.state === "current") {
    return (
      <span className={cx("flex h-7 w-7 items-center justify-center rounded-full font-mono text-xs font-semibold", CURRENT[step.tone])} aria-hidden="true">
        {index + 1}
      </span>
    );
  }
  return (
    <span
      className={cx(
        "flex h-7 w-7 items-center justify-center rounded-full border font-mono text-xs",
        step.state === "skipped" ? "border-dashed border-border text-muted-foreground/50" : "border-border text-muted-foreground",
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
                  "absolute hidden h-px sm:left-[calc(50%+1.25rem)] sm:right-[calc(-50%+1.25rem)] sm:top-3.5 sm:block",
                  steps[i + 1].state === "done" || steps[i + 1].state === "current" ? "bg-muted-foreground/60" : "bg-border",
                )}
              />
            )}
            <Marker step={step} index={i} />
            <span
              className={cx(
                "text-sm",
                step.state === "current"
                  ? cx("font-semibold", step.tone === "warning" || step.tone === "info" ? LABEL_WARN : "text-foreground")
                  : step.state === "done"
                    ? "text-muted-foreground"
                    : "text-muted-foreground/60",
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
