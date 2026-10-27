import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { categoryLabel, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

const SELECT = "rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm";
const REASONS: [string, string][] = [
  ["escalated", "Escalated"],
  ["awaiting_approval", "Waiting for a decision"],
];

function waited(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  return hours < 24 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/** Cases that need a person, in the caller's scope, oldest wait first (S7.3). */
export function QueuePage() {
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("");
  const [mine, setMine] = useState(false);
  const cats = useApi(() => api.categories(), []);
  const { data, error, loading, reload } = useApi(
    () => api.caseQueue({ reason, category, owned_by_me: mine }),
    [reason, category, mine],
  );
  const filtered = Boolean(reason || category || mine);

  return (
    <>
      <PageHeader
        title="Cases to handle"
        subtitle="Cases that need a person, with the oldest wait first. Each has an owner: the manager of the outlet, or HQ for larger amounts."
        actions={
          <button type="button" onClick={() => void reload()} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Refresh
          </button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3" role="group" aria-label="Filter cases to handle">
        <label className="text-sm text-slate-600">
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
        <label className="text-sm text-slate-600">
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
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          Owned by me
        </label>
      </div>
      {loading ? (
        <Loading label="Loading cases…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        filtered ? (
          <EmptyState title="No cases match these filters">Try a different reason or category, or clear the filters.</EmptyState>
        ) : (
          <EmptyState title="Nothing waiting for a person">You're all caught up. Escalated cases and cases waiting for a decision appear here.</EmptyState>
        )
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Case</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Reason</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Waiting</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Owner</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Language</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((c) => (
                <tr key={c.case_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{categoryLabel(c.category)}</div>
                    <div className="font-mono text-xs text-slate-500">
                      {c.order_ref ?? "—"}
                      {c.location_name ? ` · ${c.location_name}` : ""}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">
                    <Badge tone={c.reason_kind === "escalated" ? "warning" : "accent"}>
                      {c.reason_kind === "escalated" ? "Escalated" : "Waiting for a decision"}
                    </Badge>
                    <div className="mt-1 max-w-xs truncate text-xs text-slate-500" title={c.reason}>
                      {c.reason}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{waited(c.waiting_seconds)}</td>
                  <td className="px-4 py-3 text-slate-700">
                    {c.owner_name ? (c.owned_by_me ? `${c.owner_name} (you)` : c.owner_name) : "Unassigned"}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{c.language}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">{c.amount_paise == null ? "—" : formatPaise(c.amount_paise)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={c.proposal_id && c.reason_kind === "awaiting_approval" ? `/approvals/${c.proposal_id}` : `/cases/${c.case_id}`}
                      className="font-medium text-accent-700 hover:text-accent-600"
                    >
                      Open<span className="sr-only"> {categoryLabel(c.category)} on {c.order_ref}</span>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
