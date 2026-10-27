import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { DecisionResponse, PendingApproval } from "../api/types";
import { RiskBadge } from "../components/badges";
import { Alert, Badge, Button, Card, Dl, EmptyState, ErrorState, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { age, categoryLabel, formatDateTime, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

export const NEEDS_SENIOR = "This is over your approval limit or outside your outlets, so it needs a senior approver.";
export const ALREADY_DECIDED = "Someone has already decided this proposal.";

type Pending = "approved" | "rejected" | null;

export function DecisionPanel({ proposal, onDone }: { proposal: PendingApproval; onDone?: (r: DecisionResponse) => void }) {
  const [confirming, setConfirming] = useState<Pending>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DecisionResponse | null>(null);
  const [locked, setLocked] = useState(false);

  async function submit() {
    if (!confirming) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.decide(proposal.proposal_id, confirming, note.trim() || null);
      setResult(r);
      onDone?.(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setError(NEEDS_SENIOR);
      else if (err instanceof ApiError && err.status === 409) {
        setError(ALREADY_DECIDED);
        setLocked(true);
      } else setError(errorMessage(err));
      setConfirming(null);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    const approved = result.decision === "approved";
    return (
      <Alert tone={approved ? "success" : "info"}>
        <p className="font-medium">{approved ? "Approved." : "Rejected."}</p>
        <p className="mt-1">
          {approved
            ? result.execution === "queued"
              ? "The refund has been sent to the payment provider. The case shows it as confirmed only once the provider confirms it."
              : "The remedy will be carried out. The case page shows its progress."
            : "The customer's case will show that no remedy was approved."}
        </p>
        <Link to="/approvals" className="mt-2 inline-block font-medium underline">
          Back to approvals
        </Link>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone={locked ? "warning" : "danger"}>{error}</Alert>}
      {!proposal.eligible && !locked && (
        <Alert tone="warning">The checks did not pass, so this can't be approved. You can still reject it.</Alert>
      )}
      {!locked && (
        <>
          <Field label="Note (optional)" htmlFor="decision-note" hint="Saved with your decision in the audit trail.">
            <textarea id="decision-note" rows={2} maxLength={500} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {confirming ? (
            <div role="group" aria-label="Confirm decision" className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="text-sm text-slate-800">
                {confirming === "approved"
                  ? `Approve ${humanize(proposal.action).toLowerCase()} of ${formatPaise(proposal.amount_paise)} for order ${proposal.order_ref ?? ""}?`
                  : `Reject this ${humanize(proposal.action).toLowerCase()}?`}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant={confirming === "approved" ? "primary" : "danger"} onClick={submit} loading={busy}>
                  {confirming === "approved" ? "Yes, approve" : "Yes, reject"}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(null)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setConfirming("approved")} disabled={!proposal.eligible}>
                Approve
              </Button>
              <Button variant="secondary" onClick={() => setConfirming("rejected")}>
                Reject
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function ApprovalDetailPage() {
  const { proposalId = "" } = useParams();
  // There is no single-proposal endpoint in the contract, so read the queue and pick ours.
  const { data, error, loading, reload } = useApi(() => api.approvals(500), [proposalId]);

  if (loading) return <Loading label="Loading proposal…" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const p = data?.find((x) => x.proposal_id === proposalId);
  if (!p) {
    return (
      <EmptyState title="This proposal is no longer waiting" action={<Link to="/approvals" className="text-sm font-medium text-accent-700">Back to approvals</Link>}>
        It may already have been decided, or it's outside your outlets.
      </EmptyState>
    );
  }
  // `checks` mixes pass/fail booleans with values (amounts, counts) and flags (needs_*):
  // only real checks get a tick or a cross; the rest are facts shown as values.
  const entries = Object.entries(p.checks ?? {});
  const checks = entries.filter(([k, v]) => typeof v === "boolean" && !k.startsWith("needs_"));
  const facts = entries.filter(([k, v]) => typeof v !== "boolean" || k.startsWith("needs_"));
  const factValue = (k: string, v: unknown): string =>
    typeof v === "boolean" ? (v ? "Yes" : "No")
    : typeof v === "number" && k.endsWith("_paise") ? formatPaise(v)
    : String(v);

  return (
    <>
      <Link to="/approvals" className="mb-4 inline-flex text-sm text-slate-500 hover:text-slate-900">
        ← Approvals
      </Link>
      <PageHeader
        title={`${humanize(p.action)} · ${formatPaise(p.amount_paise)}`}
        subtitle={
          <>
            {categoryLabel(p.category)} · order <span className="font-mono">{p.order_ref ?? "—"}</span>
            {p.location_name && <> · {p.location_name}</>}
            {p.created_at && <> · waiting {age(p.created_at)}</>}
          </>
        }
        actions={<RiskBadge risk={p.risk} />}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card className="p-4 sm:p-5">
            <h2 className="text-sm font-semibold text-slate-900">Customer's message</h2>
            {p.customer_message ? (
              <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-slate-200 pl-3 text-sm text-slate-700">{p.customer_message}</blockquote>
            ) : (
              <p className="mt-2 text-sm text-slate-500">Not available.</p>
            )}
          </Card>

          <Card className="p-4 sm:p-5">
            <h2 className="text-sm font-semibold text-slate-900">Why this was proposed</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{p.reason || "—"}</p>
            {p.citations && p.citations.length > 0 && (
              <div className="mt-4">
                <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Policy cited</h3>
                <ul className="mt-2 flex flex-wrap gap-2" aria-label="Policy citations">
                  {p.citations.map((ct) => (
                    <li key={`${ct.doc_key}-${ct.section_ref}-${ct.version}`}>
                      <Badge tone="neutral" className="font-mono">
                        {ct.section_ref} · v{ct.version}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-slate-500">Policy text is reference only; the amount comes from the business rules, not from the text.</p>
              </div>
            )}
          </Card>

          <Card className="p-4 sm:p-5">
            <h2 className="text-sm font-semibold text-slate-900">Checks</h2>
            {checks.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">No checks reported.</p>
            ) : (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Checks">
                {checks.map(([name, ok]) =>
                  name === "fair_use_ok" && !ok ? (
                    // Fair use is a "needs a person" signal, not an invalid proposal (amber, not red).
                    <li key={name} className="flex items-start gap-2 text-sm sm:col-span-2" data-testid="fair-use-warning">
                      <span aria-hidden="true" className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700">!</span>
                      <span className="text-amber-800">
                        Repeat claimant: {String(p.checks?.fair_use_grants_30d ?? "several")} grants in 30 days (limit {String(p.checks?.fair_use_max_grants_30d ?? "set")}) — a person must decide
                      </span>
                    </li>
                  ) : (
                  <li key={name} className="flex items-center gap-2 text-sm">
                    <span
                      aria-hidden="true"
                      className={ok ? "flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700" : "flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-rose-700"}
                    >
                      {ok ? "✓" : "✗"}
                    </span>
                    <span className="text-slate-700">{humanize(name)}</span>
                    <span className="sr-only">{ok ? "passed" : "failed"}</span>
                  </li>
                  ),
                )}
              </ul>
            )}
            {facts.length > 0 && (
              <dl className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2" aria-label="Details">
                {facts.map(([name, value]) => (
                  <div key={name} className="flex justify-between gap-2 border-b border-slate-100 py-1">
                    <dt className="text-slate-500">{humanize(name.replace(/_paise$/, ""))}</dt>
                    <dd className="font-medium text-slate-800">{factValue(name, value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {p.errors.length > 0 && (
              <div className="mt-4">
                <Alert tone="warning">
                  <ul className="list-inside list-disc space-y-1">
                    {p.errors.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </Alert>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="p-4 sm:p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-900">Proposal</h2>
            <Dl
              items={[
                ["Action", humanize(p.action)],
                ["Amount", <span key="a" className="font-semibold tabular-nums">{formatPaise(p.amount_paise)}</span>],
                ["Order total", formatPaise(p.order_total_paise)],
                ["Proposed", formatDateTime(p.created_at)],
              ]}
            />
            <Link to={`/cases/${p.case_id}`} className="mt-4 inline-block text-sm font-medium text-accent-700 hover:text-accent-600">
              Open the case →
            </Link>
          </Card>
          <Card className="p-4 sm:p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-900">Your decision</h2>
            <DecisionPanel proposal={p} />
          </Card>
        </div>
      </div>
    </>
  );
}
