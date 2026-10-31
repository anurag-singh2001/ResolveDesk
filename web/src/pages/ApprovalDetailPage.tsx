import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { DecisionResponse, PendingApproval } from "../api/types";
import { AskCustomer, WAITING_FOR_CUSTOMER, isWaitingForCustomer } from "../components/AskCustomer";
import { RiskBadge } from "../components/badges";
import { RemedyBasis, SourceLinks } from "../components/DecisionSources";
import { SwitchRemedy } from "../components/SwitchRemedy";
import { Alert, Badge, Button, Card, Dl, EmptyState, ErrorState, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { age, categoryLabel, formatDateTime, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { voucherAboveOrder } from "../lib/approvals";
import { useApi } from "../lib/useApi";

export const NEEDS_SENIOR = "This is over your approval limit or outside your outlets, so it needs a senior approver.";
export const ALREADY_DECIDED = "Someone has already decided this proposal.";

type Pending = "approved" | "rejected" | null;

/** Stored reasons from the rule path start with "deterministic rule: "; people don't need that. */
export function plainReason(reason: string | null | undefined): string {
  const text = (reason ?? "").replace(/^deterministic rule:\s*/i, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "-";
}

export function DecisionPanel({ proposal, onDone, onLocked }: { proposal: PendingApproval; onDone?: (r: DecisionResponse) => void; onLocked?: () => void }) {
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
        onLocked?.();
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
        <Link to="/approvals" className="mt-2 inline-block font-medium underline underline-offset-2 hover:text-brand">
          Back to approvals
        </Link>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone={locked ? "warning" : "danger"}>{error}</Alert>}
      {isWaitingForCustomer(proposal) && (
        <Alert tone="info">{WAITING_FOR_CUSTOMER}. This can't be approved until the customer answers or the time runs out.</Alert>
      )}
      {!proposal.eligible && !locked && (
        <Alert tone="warning">The checks did not pass, so this can't be approved. You can still reject it.</Alert>
      )}
      {!locked && (
        <>
          <Field label="Note (optional)" htmlFor="decision-note" hint="Saved with your decision in the audit trail.">
            <textarea id="decision-note" rows={2} maxLength={500} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {confirming ? (
            <div role="group" aria-label="Confirm decision" className="card-chai p-3">
              <p className="text-sm text-foreground">
                {confirming === "approved"
                  ? `Approve ${humanize(proposal.action).toLowerCase()} of ${formatPaise(proposal.amount_paise)} for order ${proposal.order_ref ?? ""}?`
                  : `Reject this ${humanize(proposal.action).toLowerCase()}?`}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {/* The safe choice (Cancel) takes focus first and sits first in the tab order. */}
                <Button variant="quiet" autoFocus onClick={() => setConfirming(null)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant={confirming === "approved" ? "solid" : "danger"} onClick={submit} loading={busy}>
                  {confirming === "approved" ? "Yes, approve" : "Yes, reject"}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="solid" onClick={() => setConfirming("approved")} disabled={!proposal.eligible || isWaitingForCustomer(proposal)}>
                Approve
              </Button>
              <Button variant="outline" onClick={() => setConfirming("rejected")}>
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
  // Once decided (or found already decided) there is nothing left to approve, reject or switch.
  const [settled, setSettled] = useState(false);

  if (loading) return <Loading label="Loading proposal…" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const p = data?.find((x) => x.proposal_id === proposalId);
  if (!p) {
    return (
      <EmptyState title="This proposal is no longer waiting" action={<Link to="/approvals" className="text-sm font-medium text-foreground underline underline-offset-2 hover:text-brand">Back to approvals</Link>}>
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

  const fairUseText = (c: PendingApproval["checks"]): string => {
    const n = c?.fair_use_grants_30d;
    const m = c?.fair_use_max_grants_30d;
    const counts = typeof n === "number" && typeof m === "number" ? `: ${n} grants in 30 days (limit ${m}).` : ".";
    return `Repeat claimant${counts} A person must decide.`;
  };

  return (
    <>
      <Link to="/approvals" className="mb-4 inline-flex text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground">
        ← Approvals
      </Link>
      <PageHeader
        title={`${humanize(p.action)} · ${formatPaise(p.amount_paise)}`}
        subtitle={
          <>
            {categoryLabel(p.category)} · order <span className="font-mono">{p.order_ref ?? "-"}</span>
            {p.location_name && <> · {p.location_name}</>}
            {p.created_at && <> · waiting {age(p.created_at)}</>}
          </>
        }
        actions={<RiskBadge risk={p.risk} />}
      />
      {voucherAboveOrder(p) && !settled && (
        <div className="mb-4">
          <Alert tone="warning">
            <span data-testid="over-total-warning">
              This voucher ({formatPaise(p.amount_paise)}) is more than the order total ({formatPaise(p.order_total_paise)}), so it can't be approved. Reject it, or switch to a smaller remedy.
            </span>
          </Alert>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card className="p-4 sm:p-5">
            <h2 className="font-montserrat text-sm font-semibold text-foreground">Customer's message</h2>
            {p.customer_message ? (
              <blockquote className="mt-2 whitespace-pre-wrap border-l border-card-edge pl-3 text-sm text-foreground">{p.customer_message}</blockquote>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">Not available.</p>
            )}
          </Card>

          <Card className="p-4 sm:p-5">
            <h2 className="font-montserrat text-sm font-semibold text-foreground">Why this was proposed</h2>
            {/* The plain basis lines say it; the stored reason is engineer wording ("deterministic rule: ...") and shows only when there is no basis. */}
            {p.basis && p.basis.length > 0 ? (
              <RemedyBasis lines={p.basis} />
            ) : (
              <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{plainReason(p.reason)}</p>
            )}
            {p.sources && p.sources.length > 0 ? (
              <div className="mt-4">
                <h3 className="text-xs font-medium text-muted-foreground">Policy cited</h3>
                <SourceLinks sources={p.sources} showVersion />
                <p className="mt-2 text-xs text-muted-foreground">Policy text is reference only; the amount comes from the business rules, not from the text.</p>
              </div>
            ) : (
              p.citations && p.citations.length > 0 && (
              <div className="mt-4">
                <h3 className="text-xs font-medium text-muted-foreground">Policy cited</h3>
                <ul className="mt-2 flex flex-wrap gap-2" aria-label="Policy citations">
                  {p.citations.map((ct) => (
                    <li key={`${ct.doc_key}-${ct.section_ref}-${ct.version}`}>
                      <Badge tone="neutral" className="font-mono">
                        {ct.section_ref} · v{ct.version}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-muted-foreground">Policy text is reference only; the amount comes from the business rules, not from the text.</p>
              </div>
              )
            )}
          </Card>

          <Card className="p-4 sm:p-5">
            <h2 className="font-montserrat text-sm font-semibold text-foreground">Checks</h2>
            {checks.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">No checks reported.</p>
            ) : (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Checks">
                {checks.map(([name, ok]) =>
                  name === "fair_use_ok" && !ok ? (
                    // Fair use is a "needs a person" signal, not an invalid proposal (yellow, not red).
                    <li key={name} className="flex items-start gap-2 rounded-md border border-yellow-600/40 px-3 py-2 text-sm text-yellow-700 sm:col-span-2 dark:border-yellow-400/40 dark:text-yellow-400" data-testid="fair-use-warning">
                      <span aria-hidden="true" className="font-semibold">!</span>
                      <span>{fairUseText(p.checks)}</span>
                    </li>
                  ) : (
                    <li key={name} className="flex items-center gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className={ok ? "flex h-5 w-5 items-center justify-center rounded-full border border-green-600/40 text-xs text-green-700 dark:border-green-400/40 dark:text-green-400" : "flex h-5 w-5 items-center justify-center rounded-full border border-red-600/40 text-xs text-red-700 dark:border-red-400/40 dark:text-red-400"}
                      >
                        {ok ? "✓" : "✗"}
                      </span>
                      <span className="text-foreground">{humanize(name)}</span>
                      <span className="sr-only">{ok ? "passed" : "failed"}</span>
                    </li>
                  ),
                )}
              </ul>
            )}
            {facts.length > 0 && (
              <dl className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2" aria-label="Details">
                {facts.map(([name, value]) => (
                  <div key={name} className="flex justify-between gap-2 border-b border-border py-1">
                    <dt className="text-muted-foreground">{humanize(name.replace(/_paise$/, ""))}</dt>
                    <dd className="font-mono font-medium tabular-nums text-foreground">{factValue(name, value)}</dd>
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
            <h2 className="mb-4 font-montserrat text-sm font-semibold text-foreground">Proposal</h2>
            <Dl
              items={[
                ["Action", humanize(p.action)],
                ["Amount", <span key="a" className="font-semibold font-mono tabular-nums">{formatPaise(p.amount_paise)}</span>],
                ["Order total", <span key="t" className="font-mono tabular-nums">{formatPaise(p.order_total_paise)}</span>],
                ["Proposed", formatDateTime(p.created_at)],
              ]}
            />
            <Link to={`/cases/${p.case_id}`} className="mt-4 inline-block text-sm font-medium text-foreground underline underline-offset-2 transition-colors duration-200 hover:text-brand">
              Open the case →
            </Link>
          </Card>
          <Card className="p-4 sm:p-5">
            <h2 className="mb-4 font-montserrat text-sm font-semibold text-foreground">Your decision</h2>
            <DecisionPanel proposal={p} onDone={() => setSettled(true)} onLocked={() => setSettled(true)} />
            {!settled && (
              <div className="mt-4 border-t border-border pt-4">
                <AskCustomer proposal={p} onAsked={reload} />
              </div>
            )}
            {!settled && !isWaitingForCustomer(p) && (
              <div className="mt-4 border-t border-border pt-4">
                <SwitchRemedy proposal={p} />
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
