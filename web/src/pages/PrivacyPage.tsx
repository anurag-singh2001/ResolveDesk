import { useState } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Consents, DataHeld, ErasureRequest, PrivacyContact } from "../api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorState,
  Loading,
  PageHeader,
  numClass,
  tableClass,
  tableWrapClass,
  tdClass,
  thClass,
} from "../components/ui";
import { useApi } from "../lib/useApi";

const CHANNEL_LABEL: Record<string, string> = { whatsapp: "WhatsApp" };

const STATUS: Record<ErasureRequest["status"], { label: string; tone: "warning" | "info" | "success" }> = {
  pending_approval: { label: "Waiting for review", tone: "info" },
  deferred: { label: "Deferred", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
};

function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

function ConsentCard({ data, onChange }: { data: Consents; onChange: (c: Consents) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(purpose: string, granted: boolean) {
    setBusy(true);
    setError(null);
    try {
      onChange(await api.setConsent(purpose, granted));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <h2 className="font-montserrat text-base font-semibold text-foreground">Offers and promotions</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Help with an order never needs this. Turn it on only if you want offers from us; turn it off any time, in one click.
      </p>
      {error && <Alert>{error}</Alert>}
      <ul className="mt-3 divide-y divide-border">
        {data.consents.map((c) => {
          const label = `Marketing messages on ${CHANNEL_LABEL[c.channel] ?? c.channel}`;
          return (
            <li key={`${c.purpose}-${c.channel}`} className="flex items-center justify-between gap-3 py-3">
              <label htmlFor={`consent-${c.purpose}-${c.channel}`} className="text-sm text-foreground">
                {label}
              </label>
              <input
                id={`consent-${c.purpose}-${c.channel}`}
                type="checkbox"
                role="switch"
                className="h-5 w-5"
                checked={c.granted}
                disabled={busy}
                onChange={(e) => void toggle(c.purpose, e.target.checked)}
              />
            </li>
          );
        })}
      </ul>
      {data.history.length > 0 && (
        <details className="mt-2 text-sm text-muted-foreground">
          <summary className="cursor-pointer">History of your choices</summary>
          <ul className="mt-2 space-y-1">
            {data.history.map((h, i) => (
              <li key={i}>
                {when(h.at)}: {h.granted ? "agreed to" : "stopped"} {h.purpose} on {CHANNEL_LABEL[h.channel] ?? h.channel}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function ErasureCard() {
  const { data, error, loading, reload } = useApi(() => api.myErasureRequest(), []);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const active = data && data.status !== "completed" ? data : null;

  async function request() {
    setBusy(true);
    setFailure(null);
    try {
      await api.requestErasure();
      await reload();
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <h2 className="font-montserrat text-base font-semibold text-foreground">Erase my data</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        We remove your name, contact details and message text. Records of payments and refunds are kept, and the
        request waits while any case or refund of yours is still open.
      </p>
      {failure && <Alert>{failure}</Alert>}
      {data && (
        <div className="mt-3 text-sm" data-testid="erasure-status">
          <Badge tone={STATUS[data.status].tone}>{STATUS[data.status].label}</Badge>
          <span className="ml-2 text-muted-foreground">asked on {when(data.requested_at)}</span>
          {data.reason && <p className="mt-2 text-foreground">{data.reason}</p>}
        </div>
      )}
      {!active && (
        <div className="mt-3">
          <Button variant="danger" loading={busy} onClick={() => void request()}>
            Request erasure
          </Button>
        </div>
      )}
    </Card>
  );
}

function ContactLine({ contact }: { contact: PrivacyContact }) {
  const who = [contact.name, contact.email].filter(Boolean).join(", ");
  return (
    <p className="text-sm text-foreground" data-testid="privacy-contact">
      <span className="font-medium">{contact.label}:</span> {who}
      {who ? ". " : ""}
      {contact.response_text}
    </p>
  );
}

function HeldCard({ data }: { data: DataHeld }) {
  const h = data.headings;
  return (
    <Card className="p-5">
      <h2 className="font-montserrat text-base font-semibold text-foreground">{h.title}</h2>
      <div className={`mt-3 ${tableWrapClass}`}>
        <table className={tableClass} data-testid="held-table">
          <thead>
            <tr>
              <th scope="col" className={thClass}>{h.item}</th>
              <th scope="col" className={thClass}>{h.yours}</th>
              <th scope="col" className={thClass}>{h.purpose}</th>
              <th scope="col" className={thClass}>{h.keep}</th>
              <th scope="col" className={thClass}>{h.use}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.key} data-testid={`held-${item.key}`}>
                <th scope="row" className={`${tdClass} text-left font-medium`}>{item.label}</th>
                <td className={`${tdClass} ${numClass}`}>{item.summary}</td>
                <td className={`${tdClass} text-muted-foreground`}>{item.purpose}</td>
                <td className={`${tdClass} text-muted-foreground`}>
                  {item.retention}
                  {item.retention_provisional && data.provisional_label && (
                    <Badge tone="warning" className="ml-1">{data.provisional_label}</Badge>
                  )}
                </td>
                <td className={`${tdClass} text-muted-foreground`}>{item.use_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.processors.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-foreground">{h.processors}</h3>
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground" data-testid="held-processors">
            {data.processors.map((p) => (
              <li key={p.name}>
                {p.name} ({p.role}): {p.data}
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.not_kept.length > 0 && (
        <div className="mt-4" data-testid="held-not-kept">
          <h3 className="text-sm font-semibold text-foreground">{h.not_kept}</h3>
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
            {data.not_kept.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

export function PrivacyPage() {
  const held = useApi(() => api.dataHeld(), []);
  const consents = useApi(() => api.myConsents(), []);
  const [downloading, setDownloading] = useState(false);
  const [dlError, setDlError] = useState<string | null>(null);
  const [latest, setLatest] = useState<Consents | null>(null);

  async function download() {
    setDownloading(true);
    setDlError(null);
    try {
      const body = await api.dataExport();
      const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "my-data.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDlError(errorMessage(err));
    } finally {
      setDownloading(false);
    }
  }

  const current = latest ?? consents.data;
  return (
    <>
      <PageHeader title="Privacy & data" subtitle="Choose what we may send you, see what we hold, or ask us to erase it." />
      <div className="space-y-4">
        {held.data && (
          <Card className="p-4">
            <ContactLine contact={held.data.contact} />
          </Card>
        )}
        {held.loading ? (
          <Loading />
        ) : held.error || !held.data ? (
          <ErrorState error={held.error} onRetry={held.reload} />
        ) : (
          <HeldCard data={held.data} />
        )}
        {consents.loading ? (
          <Loading />
        ) : consents.error || !current ? (
          <ErrorState error={consents.error} onRetry={consents.reload} />
        ) : (
          <ConsentCard data={current} onChange={setLatest} />
        )}
        <Card className="p-5">
          <h2 className="font-montserrat text-base font-semibold text-foreground">Download my data</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            A copy of your details, orders, cases and choices, and the companies that process data for us.
          </p>
          {dlError && <Alert>{dlError}</Alert>}
          <div className="mt-3">
            <Button variant="outline" loading={downloading} onClick={() => void download()}>
              Download my data
            </Button>
          </div>
        </Card>
        <ErasureCard />
        {held.data && (
          <footer className="border-t border-border pt-3">
            <ContactLine contact={held.data.contact} />
          </footer>
        )}
      </div>
    </>
  );
}
