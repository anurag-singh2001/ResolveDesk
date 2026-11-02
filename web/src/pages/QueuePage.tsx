import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import type { QueueItem } from "../api/types";
import { RiskBadge } from "../components/badges";
import { Badge, Button, EmptyState, ErrorState, Loading, PageHeader, inputClass, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { categoryLabel, humanize, languageLabel } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

const SELECT = `${inputClass} w-auto py-1.5`;
const REASONS: [string, string][] = [
  ["escalated", "Escalated"],
  ["awaiting_approval", "Waiting for a decision"],
];

const SORTERS: Record<string, (a: QueueItem, b: QueueItem) => number> = {
  oldest: (a, b) => b.waiting_seconds - a.waiting_seconds,
  newest: (a, b) => a.waiting_seconds - b.waiting_seconds,
  amount_desc: (a, b) => (b.amount_paise ?? -1) - (a.amount_paise ?? -1),
};

function waited(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  return hours < 24 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/** Cases that need a person, in the caller's scope, oldest wait first (S7.3). */
export function QueuePage() {
  // In the URL so the old /approvals link lands on the same filtered list.
  const [params, setParams] = useSearchParams();
  const reason = params.get("reason") ?? "";
  const setReason = (value: string) => setParams(value ? { reason: value } : {}, { replace: true });
  const [outlet, setOutlet] = useState("");
  const [action, setAction] = useState("");
  const [sort, setSort] = useState("oldest");
  const [category, setCategory] = useState("");
  const [mine, setMine] = useState(false);
  const cats = useApi(() => api.categories(), []);
  const { data, error, loading, reload } = useApi(
    () => api.caseQueue({ reason, category, owned_by_me: mine }),
    [reason, category, mine],
  );
  const filtered = Boolean(reason || category || mine || outlet || action);
  // The list is already limited to the caller's scope, so its own outlets are the choices.
  const outlets = [...new Set((data ?? []).map((c) => c.location_name).filter((n): n is string => Boolean(n)))].sort();
  const actions = [...new Set((data ?? []).map((c) => c.action).filter((a): a is string => Boolean(a)))].sort();
  const rows = data
    ?.filter((c) => (!outlet || c.location_name === outlet) && (!action || c.action === action))
    .sort(SORTERS[sort]);

  return (
    <>
      <PageHeader
        title="Cases to handle"
        subtitle="Everything that needs a person, oldest wait first: remedies to approve and cases passed to staff. Nothing is paid or sent until a person decides."
        actions={
          <Button variant="quiet" onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3" role="group" aria-label="Filter cases to handle">
        <label className="flex items-center text-sm text-muted-foreground">
          <span className="mr-2">Reason</span>
          <select className={SELECT} value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">All reasons</option>
            {REASONS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center text-sm text-muted-foreground">
          <span className="mr-2">Outlet</span>
          <select className={SELECT} value={outlet} onChange={(e) => setOutlet(e.target.value)}>
            <option value="">All outlets</option>
            {outlets.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center text-sm text-muted-foreground">
          <span className="mr-2">Category</span>
          <select className={SELECT} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {(cats.data?.categories ?? []).map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center text-sm text-muted-foreground">
          <span className="mr-2">Action</span>
          <select className={SELECT} value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All actions</option>
            {actions.map((a) => (
              <option key={a} value={a}>
                {humanize(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center text-sm text-muted-foreground">
          <span className="mr-2">Sort</span>
          <select className={SELECT} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="oldest">Oldest first</option>
            <option value="newest">Newest first</option>
            <option value="amount_desc">Highest amount</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" className="h-4 w-4 accent-current" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          Owned by me
        </label>
      </div>
      {loading ? (
        <Loading label="Loading cases…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !rows || rows.length === 0 ? (
        filtered ? (
          <EmptyState title="No cases match these filters">Try a different reason, outlet or category, or clear the filters.</EmptyState>
        ) : (
          <EmptyState title="Nothing waiting for a person">You're all caught up. Escalated cases and cases waiting for a decision appear here.</EmptyState>
        )
      ) : (
        <div className={tableWrapClass}>
          <table className={tableClass}>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Case</th>
                <th scope="col" className={thClass}>Reason</th>
                <th scope="col" className={thClass}>Waiting</th>
                <th scope="col" className={thClass}>Owner</th>
                <th scope="col" className={thClass}>Language</th>
                <th scope="col" className={`${thClass} text-right`}>Amount</th>
                <th scope="col" className={thClass}><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.case_id}>
                  <td className={tdClass}>
                    <div className="font-medium text-foreground">{categoryLabel(c.category)}</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {c.order_ref ?? "-"}
                      {c.location_name ? ` · ${c.location_name}` : ""}
                    </div>
                  </td>
                  <td className={tdClass}>
                    <Badge tone={c.reason_kind === "escalated" ? "warning" : "purple"}>
                      {c.reason_kind === "escalated" ? "Escalated" : "Waiting for a decision"}
                    </Badge>
                    {c.risk && <span className="ml-2"><RiskBadge risk={c.risk} /></span>}
                    <div className="mt-1 max-w-xs truncate text-xs text-muted-foreground" title={c.reason}>
                      {c.reason}
                    </div>
                  </td>
                  <td className={`${tdClass} text-muted-foreground`}>{waited(c.waiting_seconds)}</td>
                  <td className={tdClass}>
                    {c.owner_name ? (c.owned_by_me ? `${c.owner_name} (you)` : c.owner_name) : "Unassigned"}
                  </td>
                  <td className={tdClass}>{languageLabel(c.language)}</td>
                  <td className={`${tdClass} text-right font-semibold ${numClass}`}>{c.amount_paise == null ? "-" : formatPaise(c.amount_paise)}</td>
                  <td className={`${tdClass} text-right`}>
                    <Link
                      to={c.proposal_id && c.reason_kind === "awaiting_approval" ? `/approvals/${c.proposal_id}` : `/cases/${c.case_id}`}
                      className="font-medium text-foreground underline underline-offset-2 transition-colors duration-200 hover:text-brand"
                    >
                      Open<span className="sr-only"> {categoryLabel(c.category)} on {c.order_ref}</span>
                    </Link>
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
