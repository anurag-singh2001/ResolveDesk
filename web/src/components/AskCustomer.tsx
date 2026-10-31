import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { AskSuggestion, PendingApproval } from "../api/types";
import { formatDateTime, humanize } from "../lib/format";
import { formatPaise, parseRupeesToPaise } from "../lib/money";
import { Alert, Button, Field, inputClass } from "./ui";

export const WAITING_FOR_CUSTOMER = "Waiting for the customer";
export const ASK_CONFLICT = "Someone has already decided or changed this proposal, or the customer was already asked.";

/** True while the customer is being asked: the proposal can't be approved until they answer. */
export function isWaitingForCustomer(p: Pick<PendingApproval, "offer">): boolean {
  return p.offer?.state === "open";
}

/**
 * An approver puts two options to the customer, then reviews the answer (S8.10). The server
 * owns which options and amounts the rules allow and re-checks everything; the rupee fields
 * only ask for an amount at or below the maximum shown. Nothing is paid by asking.
 */
export function AskCustomer({ proposal, onAsked }: { proposal: PendingApproval; onAsked?: () => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sug, setSug] = useState<AskSuggestion | null>(null);
  const [texts, setTexts] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [done, setDone] = useState(false);
  const confirmRef = useRef<HTMLDivElement>(null);

  // Cancel is the first button of the confirm step and takes focus, so Enter never confirms by accident.
  useEffect(() => {
    if (confirming) confirmRef.current?.querySelector("button")?.focus();
  }, [confirming]);

  if (proposal.offer?.state === "open") {
    return (
      <section aria-label="Waiting for the customer" className="space-y-2 rounded-lg border border-border p-3">
        <h3 className="font-montserrat text-sm font-semibold text-foreground">{WAITING_FOR_CUSTOMER}</h3>
        <p className="text-sm text-foreground">
          You asked the customer to choose between {proposal.offer.options.map((o) => `${humanize(o.kind).toLowerCase()} of ${formatPaise(o.amount_paise)}`).join(" and ")}.
          This proposal can't be approved until they answer or the time runs out ({formatDateTime(proposal.offer.expires_at)}).
        </p>
        <p className="text-xs text-muted-foreground">Nothing has been paid. You can still reject the proposal.</p>
      </section>
    );
  }
  if (proposal.offer?.state === "expired") {
    return (
      <Alert tone="info">
        <p className="font-medium">The customer did not answer.</p>
        <p className="mt-1">The question ran out of time, so this proposal is yours to decide.</p>
      </Alert>
    );
  }
  if (done) {
    return (
      <Alert tone="success">
        <p className="font-medium">{WAITING_FOR_CUSTOMER}.</p>
        <p className="mt-1">The customer can see the two options. Nothing is paid. You will review their pick before anything is approved.</p>
      </Alert>
    );
  }

  async function openPanel() {
    setOpen(true);
    setError(null);
    setLoading(true);
    try {
      const s = await api.askSuggestion(proposal.proposal_id);
      setSug(s);
      setTexts(s.options.map((o) => (o.amount_paise / 100).toFixed(2).replace(/\.00$/, "")));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(ASK_CONFLICT);
        setLocked(true);
      } else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  const amounts = texts.map((t) => parseRupeesToPaise(t));

  function problem(): string | null {
    if (!sug) return "Nothing to ask.";
    for (let i = 0; i < sug.options.length; i++) {
      const a = amounts[i];
      if (a === null || a === undefined || a <= 0) return "Enter each amount in rupees, for example 180.50.";
      if (a > sug.options[i].amount_paise) return `The most you can offer as ${humanize(sug.options[i].action).toLowerCase()} is ${formatPaise(sug.options[i].amount_paise)}.`;
    }
    return null;
  }

  async function submit() {
    if (!sug) return;
    setBusy(true);
    setError(null);
    try {
      await api.askCustomer(
        proposal.proposal_id,
        sug.options.map((o, i) => ({ action: o.action, amount_paise: amounts[i] as number })),
      );
      setDone(true);
      onAsked?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(err.message || ASK_CONFLICT);
        setLocked(true);
      } else setError(errorMessage(err));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={openPanel}>
        Ask the customer
      </Button>
    );
  }

  const blocked = sug !== null && !sug.can_ask;

  return (
    <section aria-label="Ask the customer" className="space-y-3 rounded-lg border border-border p-3">
      <h3 className="font-montserrat text-sm font-semibold text-foreground">Ask the customer</h3>
      <p className="text-xs text-muted-foreground">
        Check the policy above first. The customer chooses between two options the rules allow, then you review their pick.
        Asking pays nothing and the customer is not promised anything.
      </p>
      {error && <Alert tone={locked ? "warning" : "danger"}>{error}</Alert>}
      {loading && <p className="text-sm text-muted-foreground">Working out what the rules allow…</p>}
      {blocked && !locked && <Alert tone="warning">{sug.blocked_reason}</Alert>}
      {sug && !blocked && !locked && (
        <>
          {sug.options.map((o, i) => (
            <Field
              key={o.code}
              label={`${humanize(o.action)} (₹)`}
              htmlFor={`ask-amount-${i}`}
              hint={`Up to ${formatPaise(o.amount_paise)} (the most the rules allow).`}
            >
              <input
                id={`ask-amount-${i}`}
                inputMode="decimal"
                className={inputClass}
                value={texts[i] ?? ""}
                onChange={(e) => {
                  setTexts(texts.map((t, j) => (j === i ? e.target.value : t)));
                  setConfirming(false);
                }}
              />
            </Field>
          ))}
          <p className="text-xs text-muted-foreground">The customer has {sug.answer_days} days to answer.</p>
          {confirming ? (
            <div ref={confirmRef} role="group" aria-label="Confirm question" className="rounded-lg border border-border p-3">
              <p className="text-sm text-foreground">
                Ask the customer to choose between {sug.options.map((o, i) => `${humanize(o.action).toLowerCase()} of ${formatPaise(amounts[i] ?? 0)}`).join(" and ")}?
                The proposal can't be approved until they answer or {sug.answer_days} days pass.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="quiet" autoFocus onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="soft" onClick={submit} loading={busy}>
                  Yes, ask the customer
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  const p = problem();
                  setError(p);
                  setLocked(false);
                  if (!p) setConfirming(true);
                }}
              >
                Review question
              </Button>
              <Button variant="quiet" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </div>
          )}
        </>
      )}
      {(locked || blocked) && (
        <Button variant="quiet" onClick={() => setOpen(false)}>
          Close
        </Button>
      )}
    </section>
  );
}
