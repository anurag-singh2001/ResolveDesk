import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { Consents, DataHeld, ErasureInfo, ErasureRequest, ErasureStage, PrivacyContact } from "../api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorState,
  Loading,
  PageHeader,
  Switch,
  numClass,
  tableClass,
  tableWrapClass,
  tdClass,
  thClass,
} from "../components/ui";
import { useApi } from "../lib/useApi";


function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

function ConsentCard({ data, onChange }: { data: Consents; onChange: (c: Consents) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const b = data.benefits;

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
      <h2 className="font-montserrat text-base font-semibold text-foreground">{b.headings.title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{b.headings.intro}</p>
      {error && <Alert>{error}</Alert>}
      <ul className="mt-3 divide-y divide-border">
        {b.purposes.map((p) => (
          <li key={`${p.purpose}-${p.channel}`} className="space-y-2 py-3" data-testid={`consent-${p.purpose}`}>
            <h3 className="text-sm font-semibold text-foreground">{p.title}</h3>
            <p className="text-sm text-foreground">{p.benefit}</p>
            <p className="text-sm text-muted-foreground">
              {p.sent} {p.cap} {p.channel_label}.
            </p>
            <Switch
              id={`consent-${p.purpose}-${p.channel}`}
              label={p.switch_label}
              stateLabel={p.state_label}
              checked={p.granted}
              disabled={busy}
              onChange={(next) => void toggle(p.purpose, next)}
            />
          </li>
        ))}
        <li className="space-y-1 py-3" data-testid="consent-always-on">
          <h3 className="text-sm font-semibold text-foreground">
            {b.always_on.title}
            <Badge tone="muted" className="ml-2">{b.always_on.badge}</Badge>
          </h3>
          <p className="text-sm text-muted-foreground">{b.always_on.body}</p>
        </li>
      </ul>
      <p className="mt-2 text-sm text-foreground" data-testid="consent-note">{b.headings.note}</p>
      {b.history_labelled.length > 0 && (
        <details className="mt-3 text-sm text-muted-foreground" open>
          <summary className="cursor-pointer">{b.headings.history}</summary>
          <ul className="mt-2 space-y-1" data-testid="consent-history">
            {b.history_labelled.map((h, i) => (
              <li key={i}>
                {when(h.at)}: {h.action_label} {h.purpose_label} {h.channel_label}. {b.headings.notice}: {h.notice_version}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function List({ items, testId }: { items: ReactNode[]; testId: string }) {
  return (
    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground" data-testid={testId}>
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

function ErasureExplained({ info }: { info: ErasureInfo }) {
  const h = info.headings;
  return (
    <div className="mt-3 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{h.remove}</h3>
        <List testId="erase-remove" items={info.remove} />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{h.keep}</h3>
        <List
          testId="erase-keep"
          items={info.keep.map((k) => (
            <span key={k.key}>
              <span className="text-foreground">{k.label}.</span> {k.reason}
              {k.provisional && info.provisional_label && (
                <Badge tone="warning" className="ml-1">{info.provisional_label}</Badge>
              )}
            </span>
          ))}
        />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{h.wait}</h3>
        <List testId="erase-wait" items={info.wait} />
      </div>
      <p className="text-sm text-muted-foreground" data-testid="erase-timing">{info.timing}</p>
    </div>
  );
}

const STAGE_TONE: Record<ErasureStage, "info" | "warning" | "success" | "neutral"> = {
  received: "info",
  deferred: "warning",
  done: "success",
  withdrawn: "neutral",
};

function ErasureCard() {
  const info = useApi(() => api.erasureInfo(), []);
  const current = useApi(() => api.myErasureRequest(), []);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [latest, setLatest] = useState<ErasureRequest | null>(null);

  if (info.loading || current.loading) return <Loading />;
  if (info.error || !info.data) return <ErrorState error={info.error} onRetry={info.reload} />;
  if (current.error) return <ErrorState error={current.error} onRetry={current.reload} />;
  const text = info.data;
  const req = latest ?? current.data;
  const open = req?.can_withdraw ?? false;

  async function act(call: () => Promise<ErasureRequest>) {
    setBusy(true);
    setFailure(null);
    try {
      setLatest(await call());
      setConfirming(false);
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <h2 className="font-montserrat text-base font-semibold text-foreground">{text.title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{text.intro}</p>
      <ErasureExplained info={text} />
      {failure && <Alert>{failure}</Alert>}
      {req && (
        <div className="mt-4 border-t border-border pt-3 text-sm" data-testid="erasure-status">
          <h3 className="font-semibold text-foreground">{text.status_title}</h3>
          <p className="mt-2">
            <Badge tone={STAGE_TONE[req.stage]}>{req.stage_label}</Badge>
          </p>
          <p className="mt-2 text-foreground">{req.stage_text}</p>
          <p className="mt-1 text-muted-foreground">{req.received_text}</p>
          {req.expected_text && <p className="text-muted-foreground">{req.expected_text}</p>}
          <div className="mt-2">
            <ContactLine contact={req.contact} />
          </div>
        </div>
      )}
      {open && (
        <div className="mt-3">
          <Button variant="outline" loading={busy} onClick={() => void act(() => api.withdrawErasure())}>
            {text.buttons.withdraw}
          </Button>
        </div>
      )}
      {!open && !confirming && (
        <div className="mt-3">
          <Button variant="danger" onClick={() => setConfirming(true)}>
            {text.buttons.request}
          </Button>
        </div>
      )}
      {!open && confirming && (
        <div role="alertdialog" aria-labelledby="erase-confirm-title" className="mt-3 rounded-md border border-border p-4" data-testid="erase-confirm">
          <h3 id="erase-confirm-title" className="text-sm font-semibold text-foreground">{text.confirm.title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{text.confirm.body}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" autoFocus disabled={busy} onClick={() => setConfirming(false)}>
              {text.buttons.back}
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void act(() => api.requestErasure())}>
              {text.buttons.confirm}
            </Button>
          </div>
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
          <h3 className="text-sm font-semibold text-foreground">
            {h.processors}
            {data.provisional_label && (
              <Badge tone="warning" className="ml-2">{data.provisional_label}</Badge>
            )}
          </h3>
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
            A copy of your details, orders, cases and choices, and the companies that process data for us. The file is for other software; the readable version is for you.
          </p>
          {dlError && <Alert>{dlError}</Alert>}
          <div className="mt-3">
            <Button variant="outline" loading={downloading} onClick={() => void download()}>
              Download my data
            </Button>
            <Link
              to="/privacy/export"
              className="ml-4 text-sm font-medium text-foreground underline underline-offset-2 transition-colors duration-200 hover:text-brand"
            >
              Open readable version
            </Link>
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
