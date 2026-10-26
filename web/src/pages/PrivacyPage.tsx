import { useState } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Consents, ErasureRequest } from "../api/types";
import { Alert, Badge, Button, Card, ErrorState, Loading, PageHeader } from "../components/ui";
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
      <h2 className="text-base font-semibold text-slate-900">Offers and promotions</h2>
      <p className="mt-1 text-sm text-slate-600">
        Help with an order never needs this. Turn it on only if you want offers from us; turn it off any time, in one click.
      </p>
      {error && <Alert>{error}</Alert>}
      <ul className="mt-3 divide-y divide-slate-100">
        {data.consents.map((c) => {
          const label = `Marketing messages on ${CHANNEL_LABEL[c.channel] ?? c.channel}`;
          return (
            <li key={`${c.purpose}-${c.channel}`} className="flex items-center justify-between gap-3 py-3">
              <label htmlFor={`consent-${c.purpose}-${c.channel}`} className="text-sm text-slate-800">
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
        <details className="mt-2 text-sm text-slate-600">
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
      <h2 className="text-base font-semibold text-slate-900">Erase my data</h2>
      <p className="mt-1 text-sm text-slate-600">
        We remove your name, contact details and message text. Records of payments and refunds are kept as the law requires,
        and the request waits while any case or refund of yours is still open.
      </p>
      {failure && <Alert>{failure}</Alert>}
      {data && (
        <div className="mt-3 text-sm" data-testid="erasure-status">
          <Badge tone={STATUS[data.status].tone}>{STATUS[data.status].label}</Badge>
          <span className="ml-2 text-slate-500">asked on {when(data.requested_at)}</span>
          {data.reason && <p className="mt-2 text-slate-700">{data.reason}</p>}
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

export function PrivacyPage() {
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
        {consents.loading ? (
          <Loading />
        ) : consents.error || !current ? (
          <ErrorState error={consents.error} onRetry={consents.reload} />
        ) : (
          <ConsentCard data={current} onChange={setLatest} />
        )}
        <Card className="p-5">
          <h2 className="text-base font-semibold text-slate-900">Download my data</h2>
          <p className="mt-1 text-sm text-slate-600">
            A copy of your details, orders, cases and choices, and the companies that process data for us.
          </p>
          {dlError && <Alert>{dlError}</Alert>}
          <div className="mt-3">
            <Button variant="secondary" loading={downloading} onClick={() => void download()}>
              Download my data
            </Button>
          </div>
        </Card>
        <ErasureCard />
      </div>
    </>
  );
}
