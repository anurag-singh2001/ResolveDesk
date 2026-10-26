import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { errorMessage } from "../api/client";
import type { ChaosSettings, ClockState, SweepReport } from "../api/types";
import { Alert, Button, Card, ErrorState, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { useApi } from "../lib/useApi";

const RATE_FIELDS = [
  ["timeout_rate", "Timeout rate", "Provider never answers; nothing happened."],
  ["accept_then_timeout_rate", "Accept then timeout rate", "Provider acts, but the answer is lost."],
  ["transient_error_rate", "Transient error rate", "Temporary failure; a retry works."],
  ["error_rate", "Error rate", "Provider refuses the request."],
] as const;

type Draft = Record<"timeout_rate" | "accept_then_timeout_rate" | "transient_error_rate" | "error_rate" | "delay_ms", string>;

const toDraft = (c: ChaosSettings): Draft => ({
  timeout_rate: String(c.timeout_rate),
  accept_then_timeout_rate: String(c.accept_then_timeout_rate),
  transient_error_rate: String(c.transient_error_rate),
  error_rate: String(c.error_rate),
  delay_ms: String(c.delay_ms),
});

const PRESETS: Array<{ label: string; service: string; settings: Partial<ChaosSettings> }> = [
  { label: "Payment times out after accepting", service: "payment", settings: { accept_then_timeout_rate: 1 } },
  { label: "Payment is down (timeouts)", service: "payment", settings: { timeout_rate: 1 } },
  { label: "Vouchers time out after accepting", service: "vouchers", settings: { accept_then_timeout_rate: 1 } },
  { label: "Messaging fails", service: "messaging", settings: { error_rate: 1 } },
];

function ServiceCard({ service, current, onSaved }: { service: string; current: ChaosSettings; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<Draft>(toDraft(current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => setDraft(toDraft(current)), [current]);

  async function save(settings: Partial<ChaosSettings>) {
    setBusy(true);
    setError(null);
    try {
      await api.setChaos(service, settings);
      await onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [k]: e.target.value });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    void save({
      timeout_rate: Number(draft.timeout_rate),
      accept_then_timeout_rate: Number(draft.accept_then_timeout_rate),
      transient_error_rate: Number(draft.transient_error_rate),
      error_rate: Number(draft.error_rate),
      delay_ms: Number(draft.delay_ms),
    });
  };

  return (
    <Card className="p-4">
      <form onSubmit={submit} aria-label={`Chaos settings for ${service}`}>
        <h2 className="text-sm font-semibold capitalize text-slate-900">{service}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {RATE_FIELDS.map(([key, label, hint]) => (
            <Field key={key} label={label} htmlFor={`${service}-${key}`} hint={hint}>
              <input id={`${service}-${key}`} type="number" min={0} max={1} step={0.1} value={draft[key]} onChange={set(key)} className={inputClass} />
            </Field>
          ))}
          <Field label="Delay (ms)" htmlFor={`${service}-delay_ms`} hint="Added to every call.">
            <input id={`${service}-delay_ms`} type="number" min={0} max={30000} step={100} value={draft.delay_ms} onChange={set("delay_ms")} className={inputClass} />
          </Field>
        </div>
        {error != null && (
          <div className="mt-3">
            <Alert>{errorMessage(error)}</Alert>
          </div>
        )}
        <div className="mt-4 flex gap-2">
          <Button type="submit" loading={busy} aria-label={`Apply ${service}`}>
            Apply
          </Button>
          <Button type="button" variant="secondary" disabled={busy} aria-label={`Reset ${service}`} onClick={() => void save({})}>
            Reset
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SweepResult({ r }: { r: SweepReport }) {
  return (
    <Alert tone="success">
      <p className="font-medium">Sweep finished</p>
      <p data-testid="sweep-result" className="mt-1">
        Executed {r.executed.length}, reconciled {r.reconciled.length}, verified {r.verified.length}, escalated {r.escalated_cases.length} case(s).
      </p>
    </Alert>
  );
}

const CLOCK_STEPS = [
  ["+1h", 3600],
  ["+4h", 4 * 3600],
  ["+1 day", 86400],
  ["+15 days", 15 * 86400],
] as const;

function ClockCard() {
  const { data, error, loading, reload } = useApi(() => api.clock(), []);
  const [state, setState] = useState<ClockState | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const shown = state ?? data;

  async function move(call: () => Promise<ClockState>) {
    setBusy(true);
    setActionError(null);
    try {
      setState(await call());
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-slate-900">Simulated clock</h2>
      <p className="mt-1 text-sm text-slate-600">
        Moves the time shown, not when approvals expire. It affects what screens report (up to 60 days ahead, for every business on
        this server); approvals and payments still run on real time. Reset puts it back.
      </p>
      {loading ? (
        <Loading label="Loading clock…" />
      ) : error != null && shown == null ? (
        <div className="mt-3">
          <Alert>{errorMessage(error)}</Alert>
          <Button className="mt-2" variant="secondary" onClick={reload}>
            Retry
          </Button>
        </div>
      ) : (
        <>
          <p className="mt-3 text-sm text-slate-900">
            Simulated now: <span data-testid="clock-now">{shown ? new Date(shown.now).toLocaleString() : ""}</span>{" "}
            <span className="text-slate-500" data-testid="clock-offset">
              (offset {shown?.offset_seconds ?? 0}s)
            </span>
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {CLOCK_STEPS.map(([label, secs]) => (
              <Button key={label} variant="secondary" disabled={busy} onClick={() => void move(() => api.advanceClock(secs))}>
                {label}
              </Button>
            ))}
            <Button variant="secondary" disabled={busy} onClick={() => void move(() => api.resetClock())}>
              Reset clock
            </Button>
          </div>
        </>
      )}
      {actionError != null && (
        <div className="mt-3">
          <Alert>{errorMessage(actionError)}</Alert>
        </div>
      )}
    </Card>
  );
}

export function DevPage() {
  const { data, error, loading, reload } = useApi(() => api.chaos(), []);
  const [sweeping, setSweeping] = useState(false);
  const [report, setReport] = useState<SweepReport | null>(null);
  const [sweepError, setSweepError] = useState<unknown>(null);

  async function runSweep() {
    setSweeping(true);
    setSweepError(null);
    setReport(null);
    try {
      setReport(await api.sweep());
    } catch (err) {
      setSweepError(err);
    } finally {
      setSweeping(false);
    }
  }

  async function preset(service: string, settings: Partial<ChaosSettings>) {
    try {
      setSweepError(null);
      await api.setChaos(service, settings);
      await reload();
    } catch (err) {
      setSweepError(err);
    }
  }

  return (
    <>
      <PageHeader title="Dev panel" subtitle="Demo only. Break the mock providers on purpose and see the system recover. Affects your business only." />
      {loading ? (
        <Loading label="Loading dev controls…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <div className="space-y-6">
          <Card className="p-4">
            <h2 className="text-sm font-semibold text-slate-900">Presets</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {PRESETS.filter((p) => data && p.service in data).map((p) => (
                <Button key={p.label} variant="secondary" onClick={() => void preset(p.service, p.settings)}>
                  {p.label}
                </Button>
              ))}
            </div>
          </Card>

          {Object.entries(data ?? {}).map(([service, current]) => (
            <ServiceCard key={service} service={service} current={current} onSaved={reload} />
          ))}

          <Card className="p-4">
            <h2 className="text-sm font-semibold text-slate-900">Recovery sweep</h2>
            <p className="mt-1 text-sm text-slate-600">
              Finishes approved work that never ran, checks unfinished payments with the provider, and hands stuck cases to a person.
              Safe to run any time.
            </p>
            <div className="mt-3">
              <Button onClick={() => void runSweep()} loading={sweeping}>
                Run sweeper
              </Button>
            </div>
            <div className="mt-3">
              {report && <SweepResult r={report} />}
              {sweepError != null && <Alert>{errorMessage(sweepError)}</Alert>}
            </div>
          </Card>

          <ClockCard />

          <Card className="p-4 text-sm text-slate-600">
            <h2 className="text-sm font-semibold text-slate-900">Reseed</h2>
            <p className="mt-1">
              There is no reseed button here: it is too destructive for a web button. From a terminal, run{" "}
              <code className="rounded bg-slate-100 px-1">make seed TENANT=all</code> to reload the demo data and{" "}
              <code className="rounded bg-slate-100 px-1">make sweep</code> to run the sweeper for every business.
            </p>
          </Card>
        </div>
      )}
    </>
  );
}
