import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Alternatives, PendingApproval, SwitchAlternative, SwitchResponse } from "../api/types";
import { humanize } from "../lib/format";
import { formatPaise, parseRupeesToPaise } from "../lib/money";
import { Alert, Button, Field, inputClass } from "./ui";

export const SWITCH_CONFLICT = "Someone has already decided or switched this proposal.";

/**
 * An approver switches a pending proposal to another remedy the rules allow (S7.10). The
 * server owns the ranges and re-checks everything; what is typed here is only a request.
 * Opens lazily, so the page costs nothing until someone asks.
 */
export function SwitchRemedy({ proposal }: { proposal: PendingApproval }) {
  const [open, setOpen] = useState(false);
  const [alts, setAlts] = useState<Alternatives | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [amountText, setAmountText] = useState("");
  const [note, setNote] = useState("");
  const [approve, setApprove] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [result, setResult] = useState<SwitchResponse | null>(null);
  const confirmRef = useRef<HTMLDivElement>(null);

  // Cancel gets focus first on the confirm step, so Enter never confirms by accident.
  useEffect(() => {
    if (confirming) confirmRef.current?.querySelector("button")?.focus(); // Cancel is the first button
  }, [confirming]);

  const choice: SwitchAlternative | undefined = alts?.alternatives.find((a) => a.action === action);
  const amount = parseRupeesToPaise(amountText);

  async function openPanel() {
    setOpen(true);
    setError(null);
    setLoading(true);
    try {
      const a = await api.alternatives(proposal.proposal_id);
      setAlts(a);
      const first = a.alternatives[0];
      if (first) setAction(first.action);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(SWITCH_CONFLICT);
        setLocked(true);
      } else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  function problem(): string | null {
    if (!choice) return "Choose a remedy.";
    if (amount === null || amount <= 0) return "Enter an amount in rupees, for example 180.50.";
    if (amount < choice.min_paise || amount > choice.max_paise)
      return `The amount must be between ${formatPaise(choice.min_paise)} and ${formatPaise(choice.max_paise)}.`;
    if ((amount - choice.min_paise) % choice.step_paise !== 0) return `The amount must be in steps of ${formatPaise(choice.step_paise)}.`;
    if (alts && choice.action === alts.current_action && amount === alts.current_amount_paise) return "That is already the proposed remedy.";
    if (!note.trim()) return "Say why you are switching. It is saved in the audit trail.";
    return null;
  }

  const overYourLimit = !!choice && amount !== null && amount > choice.you_can_approve_up_to_paise;

  async function submit() {
    if (!choice || amount === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.switchRemedy(proposal.proposal_id, {
        action: choice.action,
        amount_paise: amount,
        approve: approve && !overYourLimit,
        note: note.trim(),
      });
      setResult(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(SWITCH_CONFLICT);
        setLocked(true);
      } else setError(errorMessage(err));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <Alert tone="success">
        <p className="font-medium">Remedy switched.</p>
        <p className="mt-1">
          {humanize(result.action)} of {formatPaise(result.amount_paise)} replaces the old proposal.{" "}
          {result.decision === "approved"
            ? "It is approved."
            : result.waiting_for
              ? "It is above what you can approve, so it waits for a senior approver."
              : "It now waits for a decision."}
        </p>
        <Link to={`/approvals/${result.proposal_id}`} className="mt-2 inline-block font-medium underline">
          Open the new proposal
        </Link>
      </Alert>
    );
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={openPanel}>
        Switch remedy
      </Button>
    );
  }

  const none = alts !== null && alts.alternatives.length === 0;

  return (
    <section aria-label="Switch remedy" className="space-y-3 rounded-lg border border-border p-3">
      <h3 className="font-montserrat text-sm font-semibold text-foreground">Switch remedy</h3>
      {error && <Alert tone={locked ? "warning" : "danger"}>{error}</Alert>}
      {loading && <p className="text-sm text-muted-foreground">Loading the remedies you can switch to…</p>}
      {none && !locked && <p className="text-sm text-muted-foreground">No other remedy is allowed for this case.</p>}
      {alts && !none && !locked && (
        <>
          <fieldset>
            <legend className="text-sm font-medium text-foreground">Remedy</legend>
            <div className="mt-1.5 space-y-1.5">
              {alts.alternatives.map((a) => (
                <label key={a.action} className="flex items-start gap-2 text-sm text-foreground">
                  <input
                    type="radio"
                    name="switch-action"
                    className="mt-0.5 accent-current"
                    checked={action === a.action}
                    onChange={() => {
                      setAction(a.action);
                      setConfirming(false);
                    }}
                  />
                  <span>
                    {humanize(a.action)}
                    <span className="block text-xs text-muted-foreground">
                      Between {formatPaise(a.min_paise)} and {formatPaise(a.max_paise)}
                      {a.needs_hq_above_paise !== null && `; above ${formatPaise(a.needs_hq_above_paise)} needs HQ`}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Amount (₹)" htmlFor="switch-amount">
            <input
              id="switch-amount"
              inputMode="decimal"
              className={inputClass}
              value={amountText}
              onChange={(e) => {
                setAmountText(e.target.value);
                setConfirming(false);
              }}
            />
          </Field>
          <Field label="Why are you switching?" htmlFor="switch-note" hint="Saved with the change in the audit trail.">
            <textarea id="switch-note" rows={2} maxLength={500} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <label className="flex items-start gap-2 text-sm text-foreground">
            <input type="checkbox" className="mt-0.5 accent-current" checked={approve} onChange={(e) => setApprove(e.target.checked)} />
            <span>Approve it now as well</span>
          </label>
          {approve && overYourLimit && (
            <Alert tone="warning">That amount is over your approval limit, so it will be created and wait for a senior approver.</Alert>
          )}
          {confirming && choice && amount !== null ? (
            <div ref={confirmRef} role="group" aria-label="Confirm switch" className="rounded-lg border border-border p-3">
              <p className="text-sm text-foreground">
                Replace {humanize(alts.current_action).toLowerCase()} of {formatPaise(alts.current_amount_paise)} with{" "}
                {humanize(choice.action).toLowerCase()} of {formatPaise(amount)}
                {approve && !overYourLimit ? " and approve it" : ""}? The old proposal can no longer be approved.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="quiet" onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="soft" onClick={submit} loading={busy}>
                  Yes, switch
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
                Review switch
              </Button>
              <Button variant="quiet" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </div>
          )}
        </>
      )}
      {(locked || none) && (
        <Button variant="quiet" onClick={() => setOpen(false)}>
          Close
        </Button>
      )}
    </section>
  );
}
