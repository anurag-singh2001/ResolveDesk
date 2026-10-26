import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { AuditEvent, Case, TimelineEntry } from "../api/types";
import { useAuth } from "../auth/session";
import { StageBadge } from "../components/badges";
import { StageStepper } from "../components/StageStepper";
import { Alert, Button, Card, Dl, ErrorState, Loading, PageHeader, Spinner, cx, inputClass } from "../components/ui";
import { categoryLabel, formatDateTime, humanize, shortId } from "../lib/format";
import { formatPaise } from "../lib/money";
import { isStaff } from "../lib/roles";
import { isActiveStage, stageMeta } from "../lib/stages";
import { useApi } from "../lib/useApi";
import { usePolling } from "../lib/usePolling";

/** Timeline is NEW in the contract: a 404/405 means "not available yet", not an error. */
async function loadTimeline(id: string): Promise<TimelineEntry[] | null> {
  try {
    return await api.timeline(id);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405)) return null;
    throw err;
  }
}

function remedyHeading(stage: string): string {
  if (stage === "confirmed") return "Confirmed remedy";
  if (stage === "processing") return "Approved remedy";
  if (stage === "declined") return "Proposed remedy (not approved)";
  return "Proposed remedy";
}

function Remedy({ c }: { c: Case }) {
  if (!c.action) return null;
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-slate-900">{remedyHeading(c.stage)}</h2>
      <div className="mt-3 flex items-baseline justify-between gap-3">
        <span className="text-sm text-slate-700">{humanize(c.action)}</span>
        {c.amount_paise != null && <span className="text-xl font-semibold tabular-nums text-slate-900">{formatPaise(c.amount_paise)}</span>}
      </div>
      {c.stage === "awaiting_approval" && (
        <p className="mt-2 text-xs text-slate-500">A person reviews this before anything is paid. Nothing is final until it's confirmed.</p>
      )}
    </Card>
  );
}

function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) return <p className="text-sm text-slate-500">No updates yet.</p>;
  return (
    <ol className="relative space-y-5 border-l border-slate-200 pl-5">
      {entries.map((e, i) => {
        const tone = stageMeta(e.stage).tone;
        return (
          <li key={`${e.at}-${i}`} className="relative">
            <span
              aria-hidden="true"
              className={cx(
                "absolute -left-[1.6rem] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-white",
                tone === "success" ? "bg-emerald-500" : tone === "danger" ? "bg-rose-500" : tone === "warning" ? "bg-amber-500" : tone === "info" ? "bg-sky-500" : "bg-accent-500",
              )}
            />
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <h3 className="text-sm font-medium text-slate-900">{e.title}</h3>
              <time dateTime={e.at} className="text-xs text-slate-500">
                {formatDateTime(e.at)}
              </time>
            </div>
            {e.text && <p className="mt-0.5 text-sm text-slate-600">{e.text}</p>}
          </li>
        );
      })}
    </ol>
  );
}

function ReplyBox({ caseId, onSent }: { caseId: string; onSent: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.replyToCase(caseId, text.trim());
      setText("");
      onSent();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4 sm:p-6">
      <form onSubmit={submit} className="space-y-3">
        <label htmlFor="reply" className="block text-sm font-semibold text-slate-900">
          Your reply
        </label>
        <textarea id="reply" rows={4} maxLength={2000} className={inputClass} value={text} onChange={(e) => setText(e.target.value)} />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={busy || !text.trim()}>
          {busy ? "Sending…" : "Send reply"}
        </Button>
      </form>
    </Card>
  );
}

function AuditTrail({ caseId }: { caseId: string }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function load() {
    setError(null);
    try {
      setEvents(await api.events(caseId));
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Card className="overflow-hidden">
      <details
        onToggle={(e) => {
          const isOpen = (e.currentTarget as HTMLDetailsElement).open;
          setOpen(isOpen);
          if (isOpen && events === null) void load();
        }}
      >
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-slate-900 hover:bg-slate-50">
          Audit trail <span className="font-normal text-slate-500">(staff only, raw events)</span>
        </summary>
        {open && (
          <div className="border-t border-slate-200 px-4 py-3">
            {error ? (
              <ErrorState error={error} onRetry={load} />
            ) : events === null ? (
              <div className="flex items-center gap-2 py-2 text-sm text-slate-500">
                <Spinner className="h-4 w-4" /> Loading events…
              </div>
            ) : events.length === 0 ? (
              <p className="text-sm text-slate-500">No events recorded.</p>
            ) : (
              <ol className="space-y-3">
                {events.map((ev, i) => (
                  <li key={i} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-900">{ev.event}</span>
                      <span className="text-xs text-slate-500">
                        {humanize(ev.actor_type)} · {formatDateTime(ev.occurred_at)}
                      </span>
                    </div>
                    {ev.payload && Object.keys(ev.payload).length > 0 && (
                      <pre className="mt-2 max-h-60 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-700">{JSON.stringify(ev.payload, null, 2)}</pre>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </details>
    </Card>
  );
}

export function CasePage() {
  const { caseId = "" } = useParams();
  const { me } = useAuth();
  const staff = isStaff(me?.role);
  const kase = useApi(() => api.case(caseId), [caseId]);
  const timeline = useApi(() => loadTimeline(caseId), [caseId]);

  const stage = kase.data?.stage ?? "";
  const timedOut = usePolling(isActiveStage(stage), () => {
    void kase.reload();
    void timeline.reload();
  });

  if (kase.loading) return <Loading label="Loading case…" />;
  if (kase.error || !kase.data) return <ErrorState error={kase.error} onRetry={kase.reload} />;
  const c = kase.data;

  return (
    <>
      <Link to="/cases" className="mb-4 inline-flex text-sm text-slate-500 hover:text-slate-900">
        ← {staff ? "Cases" : "My cases"}
      </Link>
      <PageHeader
        title={categoryLabel(c.category)}
        subtitle={
          <>
            Order <span className="font-mono">{c.order_ref ?? shortId(c.transaction_id)}</span>
            {c.created_at && <> · reported {formatDateTime(c.created_at)}</>}
          </>
        }
        actions={<StageBadge stage={c.stage} />}
      />

      <div className="space-y-6">
        <Card className="p-4 sm:p-6">
          <StageStepper stage={c.stage} />
          <div className="mt-6 rounded-lg bg-slate-50 px-4 py-3" aria-live="polite">
            <p className="text-sm text-slate-800">{c.message}</p>
            {isActiveStage(c.stage) && !timedOut && (
              <p className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                <Spinner className="h-3.5 w-3.5" /> Updating automatically…
              </p>
            )}
            {isActiveStage(c.stage) && timedOut && (
              <div className="mt-2 flex items-center gap-3 text-xs text-slate-500">
                This is taking longer than usual.
                <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => { void kase.reload(); void timeline.reload(); }}>
                  Refresh
                </Button>
              </div>
            )}
          </div>
        </Card>

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            {c.stage === "awaiting_info" && !staff && (
              <ReplyBox
                caseId={c.id}
                onSent={() => {
                  void kase.reload();
                  void timeline.reload();
                }}
              />
            )}
            {timeline.data !== null && (
              <Card className="p-4 sm:p-6">
                <h2 className="mb-4 text-sm font-semibold text-slate-900">Timeline</h2>
                {timeline.loading ? (
                  <Loading label="Loading timeline…" />
                ) : timeline.error ? (
                  <ErrorState error={timeline.error} onRetry={timeline.reload} />
                ) : (
                  <Timeline entries={timeline.data ?? []} />
                )}
              </Card>
            )}
            {staff && <AuditTrail caseId={c.id} />}
          </div>
          <div className="space-y-6">
            <Remedy c={c} />
            <Card className="p-4">
              <h2 className="mb-4 text-sm font-semibold text-slate-900">Case details</h2>
              <Dl
                items={[
                  ["Case", <span key="id" className="font-mono">{shortId(c.id)}</span>],
                  ["Stage", stageMeta(c.stage).label],
                  ["Category", categoryLabel(c.category)],
                ]}
              />
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
