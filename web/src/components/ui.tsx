import type { ButtonHTMLAttributes, ReactNode } from "react";
import { errorMessage } from "../api/client";
import type { Tone } from "../lib/stages";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// ChaiUI buttons. The old names keep working: primary = solid, secondary = outline, ghost = quiet.
// Only ONE solid button per screen; use soft on cards.
type Variant = "solid" | "outline" | "soft" | "quiet" | "danger" | "primary" | "secondary" | "ghost";

const VARIANT: Record<Variant, string> = {
  solid:
    "btn-asym h-9 gap-2 bg-neutral-900 px-4 text-white hover:bg-black/90 dark:bg-white dark:text-black dark:hover:bg-neutral-200",
  outline: "btn-asym-mirror h-9 gap-2 border border-border bg-transparent px-4 text-foreground hover:bg-neutral-100 dark:hover:bg-white/5",
  soft: "h-8 rounded-md bg-primary px-3 font-semibold text-primary-foreground hover:bg-primary/90",
  quiet: "h-8 rounded-md px-2.5 text-muted-foreground hover:bg-muted hover:text-foreground",
  danger:
    "h-9 rounded-md border border-red-600/50 px-4 text-red-700 hover:bg-red-600/10 dark:border-red-400/50 dark:text-red-400",
  primary: "",
  secondary: "",
  ghost: "",
};
VARIANT.primary = VARIANT.solid;
VARIANT.secondary = VARIANT.outline;
VARIANT.ghost = VARIANT.quiet;

function ArrowUpRight() {
  return (
    <svg viewBox="0 0 16 16" className="-ml-1 h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4.5 11.5l7-7M5.5 4.5h6v6" />
    </svg>
  );
}

export function Button({
  variant = "primary",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  const solid = variant === "solid" || variant === "primary";
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 text-sm font-medium transition-colors duration-200",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT[variant],
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
      {solid && !loading && <ArrowUpRight />}
    </button>
  );
}

// Status is coloured text on a thin outline. Never a filled pill.
type BadgeTone = Tone | "purple" | "muted" | "live";

const TONE: Record<BadgeTone, string> = {
  neutral: "border-border text-foreground",
  accent: "border-border text-foreground",
  success: "border-green-600/40 text-green-700 dark:border-green-400/40 dark:text-green-400",
  warning: "border-yellow-600/40 text-yellow-700 dark:border-yellow-400/40 dark:text-yellow-400",
  danger: "border-red-600/40 text-red-700 dark:border-red-400/40 dark:text-red-400",
  info: "border-yellow-600/40 text-yellow-700 dark:border-yellow-400/40 dark:text-yellow-400",
  purple: "border-purple-600/40 text-purple-700 dark:border-purple-400/40 dark:text-purple-400",
  muted: "border-border text-muted-foreground",
  live: "border-border text-foreground",
};

export function Badge({ tone = "neutral", children, className }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE[tone],
        className,
      )}
    >
      {tone === "live" && <span className="live-dot h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("card-chai", className)}>{children}</div>;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("animate-spin text-current motion-reduce:animate-none", className ?? "h-5 w-5")} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
      <Spinner className="h-5 w-5" />
      {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card-chai flex flex-col items-center justify-center border-dashed px-6 py-14 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-border text-muted-foreground" aria-hidden="true">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M3 7h18M5 7l1 13h12l1-13M9 7V4h6v3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <h3 className="font-montserrat text-sm font-semibold text-foreground">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="card-chai px-4 py-4 text-sm">
      <p className="font-medium text-red-700 dark:text-red-400">We couldn't load this.</p>
      <p className="mt-1 text-muted-foreground">{errorMessage(error)}</p>
      {onRetry && (
        <Button variant="outline" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Alert({ tone = "danger", children }: { tone?: "danger" | "warning" | "success" | "info"; children: ReactNode }) {
  // Coloured text on a hairline card; the border stays warm and neutral.
  const text = {
    danger: "text-red-700 dark:text-red-400",
    warning: "text-yellow-700 dark:text-yellow-400",
    success: "text-green-700 dark:text-green-400",
    info: "text-foreground",
  }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cx("card-chai px-3.5 py-3 text-sm", text)}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  highlight,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  /** One cream phrase at most; shown at the end of the lead line. */
  highlight?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-medium tracking-tight text-foreground sm:text-3xl">{title}</h1>
        {(subtitle || highlight) && (
          <p className="mt-1.5 text-sm text-muted-foreground sm:text-base">
            {subtitle}
            {subtitle && highlight ? " " : null}
            {highlight && <span className="highlight">{highlight}</span>}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-foreground">
        {label}
      </label>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "block w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60";

// Table styling helpers: warm hairline rows, column heads are data labels (the one place caps are fine).
export const tableWrapClass = "card-chai overflow-x-auto";
export const tableClass = "w-full border-collapse text-sm";
export const thClass = "border-b border-border px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground";
export const tdClass = "border-b border-border px-4 py-3 align-top text-foreground";
export const numClass = "font-mono tabular-nums";

/** A labelled on/off switch. The label and the state word are always visible, so the control
 * never relies on colour alone. The caller passes the saved state (the component never
 * pre-sets it) and both positions have the same weight. */
export function Switch({
  id,
  label,
  stateLabel,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  stateLabel: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span id={`${id}-label`} className="text-sm text-foreground">
        {label}
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="inline-flex items-center gap-2 rounded-full border border-border px-2.5 py-1 text-xs font-medium text-foreground disabled:opacity-50"
      >
        <span
          aria-hidden="true"
          className={cx("h-3 w-3 rounded-full border border-foreground", checked ? "bg-foreground" : "bg-transparent")}
        />
        {stateLabel}
      </button>
    </div>
  );
}

export function Dl({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{k}</dt>
          <dd className="mt-0.5 text-sm text-foreground">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
