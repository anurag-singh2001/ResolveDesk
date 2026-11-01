import { useState, type FormEvent } from "react";
import { api } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { Alert, Button, Card, Field, inputClass } from "../components/ui";
import { formatPaise, parseRupeesToPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

/** S12.7: HQ enters offline spend (e.g. aggregator ads) in rupees. The amount is turned into
 * integer paise with digit maths here and checked again by POST /growth/spend. */
export function ManualSpendPanel() {
  const { data, reload } = useApi(() => api.channelMix(), []);
  const [channel, setChannel] = useState("aggregator_ads");
  const [rupees, setRupees] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const paise = parseRupeesToPaise(rupees);
    if (paise === null || paise <= 0) {
      setError("Enter an amount in rupees above zero, with at most two decimals, for example 1500 or 1500.50.");
      return;
    }
    if (!start || !end) {
      setError("Choose the first and last day the spend covers.");
      return;
    }
    if (end < start) {
      setError("The last day cannot be before the first day.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.enterSpend({ channel: channel.trim(), amount_paise: paise, period_start: start, period_end: end });
      setRupees("");
      setSaved(true);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const rows = data?.manual_spend ?? [];
  return (
    <Card className="mt-6 p-4">
      <h2 className="font-montserrat text-sm font-semibold text-foreground">Add spend by hand</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">
        For spend that happens outside the app, such as aggregator ads. It is kept as you type it and is not verified.
      </p>
      <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => void submit(e)} noValidate>
        <Field label="Channel" htmlFor="spend-channel" hint="A short lowercase name, for example aggregator_ads.">
          <input id="spend-channel" className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value)} />
        </Field>
        <Field label="Amount (₹)" htmlFor="spend-amount">
          <input id="spend-amount" className={inputClass} inputMode="decimal" value={rupees} onChange={(e) => setRupees(e.target.value)} />
        </Field>
        <Field label="From" htmlFor="spend-start">
          <input id="spend-start" type="date" className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field label="To" htmlFor="spend-end">
          <input id="spend-end" type="date" className={inputClass} value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Button type="submit" variant="soft" loading={busy}>
            Save spend
          </Button>
        </div>
      </form>
      {error && (
        <div className="mt-3">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {saved && (
        <div className="mt-3">
          <Alert tone="info">Saved. It now counts in the channel totals.</Alert>
        </div>
      )}
      {rows.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-muted-foreground" data-testid="manual-spend-list">
          {rows.map((r) => (
            <li key={r.id}>
              {formatPaise(r.amount_paise)} on {r.channel}, {r.period_start} to {r.period_end} (entered by hand, not verified)
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
