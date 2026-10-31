import { useState } from "react";
import { api } from "../api/endpoints";
import type { PrivacyDryRun, PrivacyQueueItem } from "../api/types";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { useApi } from "../lib/useApi";

const REMOVE_LABEL: Record<string, string> = {
  messages: "Message texts",
  name: "Name",
  contact_fields: "Phone and email",
  profile_fields: "Profile details",
  login: "Login",
  marketing_consents: "Marketing consents switched off",
};
const KEEP_LABEL: Record<string, string> = {
  orders: "Orders",
  refund_operations: "Refund records",
  cases: "Cases",
  tickets: "Tickets",
  proposals: "Remedy proposals",
  approvals: "Approvals",
  executions: "Executions",
  consent_history: "Consent history",
};

function daysLeftText(item: PrivacyQueueItem): string {
  if (item.overdue) return `${Math.abs(item.days_left)} days late`;
  return item.days_left === 1 ? "1 day left" : `${item.days_left} days left`;
}

function Counts({ title, labels, counts }: { title: string; labels: Record<string, string>; counts: Record<string, number> }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
        {Object.keys(labels).map((k) => (
          <li key={k} className="flex justify-between gap-4">
            <span>{labels[k]}</span>
            <span className={`${numClass} text-foreground`}>{counts[k] ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Review({ item, onDone, onClose }: { item: PrivacyQueueItem; onDone: () => void; onClose: () => void }) {
  const { data, error, loading, reload } = useApi(() => api.privacyDryRun(item.id), [item.id]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function approve(d: PrivacyDryRun) {
    setBusy(true);
    setFailure(null);
    try {
      await api.approveErasure(item.id, d);
      onDone();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Could not approve this request.");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-foreground">What approving would do</h2>
          <p className="mt-1 text-sm text-muted-foreground">Customer {item.customer_ref}. Counts only; no message text is shown.</p>
        </div>
        <Button variant="quiet" onClick={onClose}>
          Close
        </Button>
      </div>
      {loading ? (
        <Loading label="Checking what would be erased…" />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <>
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            <Counts title="Will be removed" labels={REMOVE_LABEL} counts={data.remove} />
            <Counts title="Will be kept" labels={KEEP_LABEL} counts={data.keep} />
          </div>
          {data.deferred ? (
            <div className="mt-4">
              <Alert tone="warning">
                Cannot be erased yet: {data.deferred.reason} Approving now keeps the request waiting and re-checks it each time.
              </Alert>
            </div>
          ) : null}
          {failure ? (
            <div className="mt-4" role="alert">
              <Alert tone="danger">{failure}</Alert>
              <Button className="mt-2" variant="outline" onClick={() => void reload()}>
                Review again
              </Button>
            </div>
          ) : null}
          <p className="mt-4 text-xs text-muted-foreground">
            This review is valid until {formatDateTime(data.expires_at)}. If the customer's data changes first, you will be asked to review again.
          </p>
          {!confirming ? (
            <div className="mt-3">
              <Button variant="outline" onClick={() => setConfirming(true)} disabled={Boolean(failure)}>
                {data.deferred ? "Approve and keep waiting" : "Approve erasure"}
              </Button>
            </div>
          ) : (
            <div role="alertdialog" aria-labelledby="pq-confirm-title" className="mt-3 rounded-md border border-border p-4" data-testid="pq-confirm">
              <h3 id="pq-confirm-title" className="text-sm font-semibold text-foreground">
                {data.deferred ? "Approve this request?" : "Erase this customer's data?"}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {data.deferred
                  ? "Nothing is erased while the reason above applies."
                  : "The listed items are removed and cannot be restored. The kept records stay."}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="outline" autoFocus disabled={busy} onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
                <Button variant="solid" loading={busy} onClick={() => void approve(data)}>
                  {data.deferred ? "Approve" : "Erase now"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

export function PrivacyRequestsPage() {
  const { data, error, loading, reload } = useApi(() => api.privacyQueue(), []);
  const [open, setOpen] = useState<PrivacyQueueItem | null>(null);

  return (
    <>
      <PageHeader
        title="Privacy requests"
        subtitle="Erasure requests waiting for a decision. We aim to answer each one within"
        highlight={data ? `${data.target_days} days` : "our target"}
        actions={
          <Button type="button" variant="quiet" onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />
      {open ? (
        <Review
          item={open}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            void reload();
          }}
        />
      ) : null}
      {loading ? (
        <Loading label="Loading privacy requests…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No open privacy requests">Requests that are withdrawn or completed leave this list.</EmptyState>
      ) : (
        <div className={tableWrapClass}>
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={thClass}>Customer</th>
                <th className={thClass}>Stage</th>
                <th className={thClass}>Received</th>
                <th className={thClass}>Target date</th>
                <th className={thClass}>Time left</th>
                <th className={thClass}>Why waiting</th>
                <th className={thClass}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td className={`${tdClass} ${numClass}`}>{item.customer_ref}</td>
                  <td className={tdClass}>
                    <Badge tone={item.stage === "deferred" ? "warning" : "neutral"}>{item.stage === "deferred" ? "Deferred" : "Received"}</Badge>
                  </td>
                  <td className={tdClass}>{formatDateTime(item.received_at)}</td>
                  <td className={tdClass}>{formatDateTime(item.target_at)}</td>
                  <td className={tdClass}>
                    <Badge tone={item.overdue ? "danger" : "muted"}>{daysLeftText(item)}</Badge>
                  </td>
                  <td className={tdClass}>{item.reason ?? "Not waiting"}</td>
                  <td className={tdClass}>
                    <Button variant="outline" onClick={() => setOpen(item)}>
                      Review
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
