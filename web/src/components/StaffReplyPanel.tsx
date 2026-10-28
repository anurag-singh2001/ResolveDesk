import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Case } from "../api/types";
import { useApi } from "../lib/useApi";
import { formatDateTime, humanize } from "../lib/format";
import { Alert, Button, Card, Field, inputClass } from "./ui";

function newKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  }
}

/** Staff: reply to the customer from a template (+ optional note) and close the case. */
export function StaffReplyPanel({ kase, onChanged }: { kase: Case; onChanged: () => void }) {
  const opts = useApi(() => api.replyTemplates(kase.id), [kase.id, kase.closed, (kase.staff_messages ?? []).length]);
  const [templateId, setTemplateId] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  // One key per form fill: a double click or a retry is the same message on the server.
  const key = useRef(newKey());

  const data = opts.data;
  if (kase.closed) {
    return (
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-slate-900">Closed</h2>
        <p className="mt-1 text-sm text-slate-600">
          {data?.close_reasons.find((r) => r.id === kase.close_reason)?.label ?? humanize(kase.close_reason ?? "closed")}. No further replies can be sent.
        </p>
        <Sent kase={kase} />
      </Card>
    );
  }
  if (!data) return null; // still loading, or not available: show nothing rather than guess
  const chosen = data.templates.find((x) => x.id === templateId);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!chosen || busy) return;
    setBusy(true);
    setError(null);
    setSent(false);
    try {
      await api.staffReply(kase.id, { template_id: chosen.id, note: note.trim() || undefined, idempotency_key: key.current });
      key.current = newKey();
      setTemplateId("");
      setNote("");
      setSent(true);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function close() {
    if (!reason || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.closeCase(kase.id, reason);
      setConfirming(false);
      onChanged();
    } catch (err) {
      setConfirming(false);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4 sm:p-6">
      <h2 className="text-sm font-semibold text-slate-900">Reply to the customer</h2>
      <form onSubmit={send} className="mt-3 space-y-3">
        <Field label="Message" htmlFor="staff-template" hint={`Sent in the customer's language (${data.language}). Figures are filled in by the system.`}>
          <select id="staff-template" className={inputClass} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">Choose a message…</option>
            {data.templates.map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}
              </option>
            ))}
          </select>
        </Field>
        {chosen && (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700" aria-label="Preview">
            {chosen.preview}
          </p>
        )}
        <Field
          label="Note from our team (optional)"
          htmlFor="staff-note"
          hint="Shown to the customer as “From our team”. Do not mention refunds, payments or amounts, and do not add links."
        >
          <textarea id="staff-note" rows={2} maxLength={data.note_max_length} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <p className="text-xs text-slate-500">
          {note.length}/{data.note_max_length}
        </p>
        {error && <Alert>{error}</Alert>}
        {sent && <Alert tone="success">Sent to the customer.</Alert>}
        <Button type="submit" loading={busy} disabled={!chosen}>
          Send to customer
        </Button>
      </form>

      <div className="mt-6 border-t border-slate-200 pt-4">
        <h3 className="text-sm font-semibold text-slate-900">Close this case</h3>
        <div className="mt-2">
          <Field label="Reason" htmlFor="close-reason">
            <select id="close-reason" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} disabled={confirming}>
              <option value="">Choose a reason…</option>
              {data.close_reasons.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {confirming ? (
          <div role="group" aria-label="Confirm close" className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm text-slate-800">
              Close this case as “{data.close_reasons.find((r) => r.id === reason)?.label}”? The customer is told, and it cannot be reopened.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="ghost" autoFocus onClick={() => setConfirming(false)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="danger" onClick={close} loading={busy}>
                Yes, close the case
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="secondary" className="mt-3" disabled={!reason} onClick={() => setConfirming(true)}>
            Close case…
          </Button>
        )}
      </div>
      <Sent kase={kase} />
    </Card>
  );
}

function Sent({ kase }: { kase: Case }) {
  const msgs = kase.staff_messages ?? [];
  if (msgs.length === 0) return null;
  return (
    <div className="mt-6 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-900">Sent to the customer</h3>
      <ul className="mt-2 space-y-2">
        {msgs.map((m, i) => (
          <li key={`${m.at}-${i}`} className="text-sm text-slate-700">
            <span className="text-xs text-slate-500">
              {formatDateTime(m.at)} · {m.kind === "note" ? "Note from our team" : "Message"}
            </span>
            <p>{m.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
