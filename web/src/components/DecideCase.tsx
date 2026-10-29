import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { ProposedRemedy, StaffRemedyOptions } from "../api/types";
import { categoryLabel, humanize } from "../lib/format";
import { formatPaise, parseRupeesToPaise } from "../lib/money";
import { Alert, Button, Card, Field, inputClass } from "./ui";

/** "Decide this case": for staff, on a case that needs a person. It only offers what the server
 *  says is allowed (GET remedy-options); the server checks every value again. When the case
 *  does not need a person the options call fails and nothing is shown. */
export function DecideCase({ caseId, stage, onChanged }: { caseId: string; stage: string; onChanged: () => void }) {
  const [opts, setOpts] = useState<StaffRemedyOptions | null>(null);
  const [sent, setSent] = useState<ProposedRemedy | null>(null);
  const [action, setAction] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sent) return;
    let live = true;
    api
      .staffRemedyOptions(caseId)
      .then((o) => live && setOpts(o))
      .catch(() => live && setOpts(null));
    return () => {
      live = false;
    };
  }, [caseId, stage, sent]);

  if (sent) {
    return (
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-foreground">Decide this case</h2>
        <p className="mt-3 text-sm text-foreground" role="status">
          {humanize(sent.action)} of {formatPaise(sent.amount_paise)}{" "}
          {sent.status === "awaiting_approval" ? "is awaiting approval by someone else." : `is already ${sent.status}.`}
        </p>
        {sent.needs_hq && <p className="mt-2 text-xs text-muted-foreground">This amount needs an HQ owner to approve it.</p>}
      </Card>
    );
  }
  if (!opts) return null;

  const chosen = opts.options.find((o) => o.action === action) ?? opts.options[0];

  async function pickCategory(category: string) {
    if (!category) return;
    setBusy(true);
    setError(null);
    try {
      setOpts(await api.categorise(caseId, category));
      setAction("");
      setAmount("");
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const paise = parseRupeesToPaise(amount);
    if (!chosen || busy) return;
    if (paise === null) {
      setError("Enter the amount in rupees, for example 120 or 120.50.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSent(await api.proposeRemedy(caseId, chosen.action, paise));
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">Decide this case</h2>
      <div className="space-y-3">
        <Field label="Category" htmlFor="decide-category">
          <select id="decide-category" className={inputClass} value={opts.category ?? ""} disabled={busy} onChange={(e) => void pickCategory(e.target.value)}>
            {!opts.category && <option value="">Choose a category</option>}
            {opts.categories.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(c)}
              </option>
            ))}
          </select>
        </Field>
        {opts.options.length === 0 && opts.note && <p className="text-xs text-muted-foreground">{opts.note}</p>}
        {chosen && (
          <form onSubmit={submit} className="space-y-3">
            <Field label="Remedy" htmlFor="decide-action">
              <select id="decide-action" className={inputClass} value={chosen.action} onChange={(e) => setAction(e.target.value)}>
                {opts.options.map((o) => (
                  <option key={o.action} value={o.action}>
                    {humanize(o.action)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Amount (₹)" htmlFor="decide-amount" hint={`Allowed: ${formatPaise(chosen.min_paise)} to ${formatPaise(chosen.max_paise)}`}>
              <input id="decide-amount" inputMode="decimal" className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Button type="submit" variant="soft" disabled={busy || !amount.trim()}>
              {busy ? "Sending…" : "Propose for approval"}
            </Button>
          </form>
        )}
        {error && <Alert>{error}</Alert>}
      </div>
    </Card>
  );
}
