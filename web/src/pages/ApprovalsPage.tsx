import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { RiskBadge } from "../components/badges";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { age, categoryLabel, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

export function ApprovalsPage() {
  const { data, error, loading, reload } = useApi(() => api.approvals(200), []);
  // HQ sees every outlet, so the outlet column matters most there; show it whenever the API sends it.
  const showOutlet = (data ?? []).some((p) => p.location_name);

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Remedies the system proposed that need a person's decision. Oldest first."
        actions={
          <button type="button" onClick={() => void reload()} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Refresh
          </button>
        }
      />
      {loading ? (
        <Loading label="Loading approvals…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState title="Nothing to approve">You're all caught up. New proposals appear here as customers report problems.</EmptyState>
      ) : (
        <>
          {/* Phone: cards */}
          <ul className="space-y-3 md:hidden">
            {data.map((p) => (
              <li key={p.proposal_id}>
                <Link to={`/approvals/${p.proposal_id}`} className="block">
                  <Card className="p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium text-slate-900">{categoryLabel(p.category)}</div>
                        <div className="font-mono text-xs text-slate-500">{p.order_ref ?? "—"}</div>
                      </div>
                      <RiskBadge risk={p.risk} />
                    </div>
                    <div className="mt-3 flex items-end justify-between">
                      <span className="text-xs text-slate-500">
                        {p.location_name ? `${p.location_name} · ` : ""}
                        {age(p.created_at)}
                      </span>
                      <span className="font-semibold tabular-nums">
                        {humanize(p.action)} {formatPaise(p.amount_paise)}
                      </span>
                    </div>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
          {/* Desktop: table */}
          <Card className="hidden overflow-hidden md:block">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Category</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Order</th>
                  {showOutlet && <th scope="col" className="px-4 py-2.5 font-medium">Outlet</th>}
                  <th scope="col" className="px-4 py-2.5 font-medium">Action</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Risk</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Age</th>
                  <th scope="col" className="px-4 py-2.5"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.map((p) => (
                  <tr key={p.proposal_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {categoryLabel(p.category)}
                      {!p.eligible && (
                        <Badge tone="danger" className="ml-2">
                          Checks failed
                        </Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{p.order_ref ?? "—"}</td>
                    {showOutlet && <td className="px-4 py-3 text-slate-700">{p.location_name ?? "—"}</td>}
                    <td className="px-4 py-3 text-slate-700">{humanize(p.action)}</td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">{formatPaise(p.amount_paise)}</td>
                    <td className="px-4 py-3"><RiskBadge risk={p.risk} /></td>
                    <td className="px-4 py-3 text-slate-500">{age(p.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Link to={`/approvals/${p.proposal_id}`} className="font-medium text-accent-700 hover:text-accent-600">
                        Review<span className="sr-only"> {categoryLabel(p.category)} on {p.order_ref}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </>
  );
}
