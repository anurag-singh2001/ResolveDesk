import { useState } from "react";
import { api } from "../api/endpoints";
import { errorMessage } from "../api/client";
import type { Campaign, GrowthSignal } from "../api/types";
import { Alert, Badge, Button, Card, Dl, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";
import { useAuth } from "../auth/session";

/** Basis points → "12.3%" with integer maths. */
function pct(bp: number): string {
  return `${Math.floor(bp / 100)}.${String(bp % 100).padStart(2, "0").slice(0, 1)}%`;
}

function CampaignPanel({ signalId, campaignId, location }: { signalId: string; campaignId: string; location: string }) {
  const { data, error, loading, reload } = useApi(() => api.campaign(campaignId), [campaignId]);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const current = campaign ?? data;

  async function run(call: () => Promise<Campaign>) {
    setBusy(true);
    setActionError(null);
    try {
      setCampaign(await call());
    } catch (err) {
      setActionError(errorMessage(err)); // the server's own words, e.g. why this approver can't count
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label="Loading campaign…" />;
  if (error || !current) return <ErrorState error={error} onRetry={reload} />;

  const pending = current.status === "pending_approval";
  const approved = current.approvals.filter((a) => a.decision === "approved");
  return (
    <div className="mt-4 space-y-3 border-t border-slate-100 pt-4" data-testid={`campaign-${signalId}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Win-back campaign for {location}</h3>
        <Badge tone={current.status === "rejected" ? "danger" : current.fully_approved ? "success" : "warning"}>
          {humanize(current.status)}
        </Badge>
      </div>
      <Dl
        items={[
          ["Audience (offer sent)", `${current.treatment_n} customers`],
          ["Holdout (no offer, for comparison)", `${current.holdout_n} customers`],
          ["Budget", formatPaise(current.budget_paise)],
          ["Approvals so far", `${approved.length} of 2: ${approved.map((a) => humanize(a.role)).join(", ") || "none yet"}`],
          ["Approval needed by", formatDateTime(current.expires_at)],
          ["Sent", current.sent_at ? formatDateTime(current.sent_at) : "Not sent"],
        ]}
      />
      {pending && (
        <>
          <Alert tone="info">
            Sending needs two different approvers, and at least one must be an HQ owner. You cannot approve twice. The
            system checks this when you decide.
          </Alert>
          <div className="flex gap-2">
            <Button loading={busy} onClick={() => void run(() => api.decideCampaign(current.id, "approved"))}>
              Approve campaign
            </Button>
            <Button variant="secondary" loading={busy} onClick={() => void run(() => api.decideCampaign(current.id, "rejected"))}>
              Reject campaign
            </Button>
          </div>
        </>
      )}
      {actionError && <Alert tone="danger">{actionError}</Alert>}
      {current.playbook ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm" data-testid="playbook">
          <div className="font-medium text-slate-900">Verdict: {humanize(current.playbook.verdict)}</div>
          <p className="mt-1 text-slate-700">{current.playbook.lesson}</p>
          <p className="mt-1 text-xs text-slate-500">
            {current.playbook.confidence_note} ({current.playbook.treatment_n} offered, {current.playbook.holdout_n} held out)
          </p>
        </div>
      ) : (
        current.sent_at && (
          <Button variant="secondary" loading={busy} onClick={() => void run(() => api.campaignVerdict(current.id))}>
            Measure result
          </Button>
        )
      )}
    </div>
  );
}

function SignalCard({ signal, location }: { signal: GrowthSignal; location: string }) {
  const [campaignId, setCampaignId] = useState<string | null>(signal.campaign_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const findings = signal.diagnosis.findings ?? [];
  const hypotheses = signal.diagnosis.hypotheses ?? [];

  async function propose() {
    setBusy(true);
    setError(null);
    try {
      setCampaignId((await api.proposeCampaign(signal.id)).id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{location}: repeat customers down</h2>
          <p className="mt-0.5 text-sm text-slate-600">
            {pct(signal.baseline_bp)} before ({signal.baseline_n} orders), {pct(signal.recent_bp)} now ({signal.recent_n} orders),
            down {pct(signal.drop_bp)} points.
          </p>
        </div>
        <Badge>{humanize(signal.status)}</Badge>
      </div>
      {findings.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700" aria-label="What the data shows">
          {findings.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
      {hypotheses.length > 0 && (
        <div className="mt-2 text-sm text-slate-600">
          <span className="font-medium">Possible causes (not confirmed):</span>
          <ul className="list-disc pl-5">
            {hypotheses.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </div>
      )}
      {campaignId ? (
        <CampaignPanel signalId={signal.id} campaignId={campaignId} location={location} />
      ) : (
        <div className="mt-4">
          <Button loading={busy} onClick={() => void propose()}>
            Propose win-back campaign
          </Button>
          {error && (
            <div className="mt-3">
              <Alert tone="danger">{error}</Alert>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export function GrowthPage() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useApi(() => api.growthSignals(), []);
  const { data: locations } = useApi(() => api.locations(), []);
  const [signals, setSignals] = useState<GrowthSignal[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const list = signals ?? data;
  const names = new Map((locations ?? []).map((l) => [l.id, l.name]));

  async function refresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      setSignals(await api.refreshSignals());
    } catch (err) {
      setRefreshError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Growth"
        subtitle="Outlets where repeat customers are dropping, and win-back campaigns to test. Nothing is sent without two approvals."
        actions={
          me?.role === "hq_owner" ? (
            <Button variant="secondary" loading={refreshing} onClick={() => void refresh()}>
              Refresh signals
            </Button>
          ) : undefined
        }
      />
      {refreshError && (
        <div className="mb-4">
          <Alert tone="danger">{refreshError}</Alert>
        </div>
      )}
      {loading ? (
        <Loading label="Loading signals…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !list || list.length === 0 ? (
        <EmptyState title="No signals right now">When an outlet's repeat-customer rate drops meaningfully, it shows up here.</EmptyState>
      ) : (
        <ul className="space-y-4">
          {list.map((s) => (
            <li key={s.id}>
              <SignalCard signal={s} location={names.get(s.location_id) ?? "Outlet"} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
