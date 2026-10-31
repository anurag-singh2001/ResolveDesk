import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import type { PendingApproval } from "../api/types";
import { approvalFlag } from "../lib/approvals";
import { RiskBadge } from "../components/badges";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { age, categoryLabel, humanize } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

const ACTIONS = ["refund", "free_item_voucher", "loyalty_credit", "send_status_update"];
const SORTS: [string, string][] = [
  ["oldest", "Oldest first"],
  ["newest", "Newest first"],
  ["amount_desc", "Highest amount"],
];
const SELECT =
  "rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring";

function FlagBadge({ p, className }: { p: PendingApproval; className?: string }) {
  const flag = approvalFlag(p);
  return flag ? (
    <Badge tone={flag.tone} className={className}>
      {flag.label}
    </Badge>
  ) : null;
}

export function ApprovalsPage() {
  // Filters live in the URL so a reload (or a shared link) keeps them.
  const [params, setParams] = useSearchParams();
  const location_id = params.get("location_id") ?? "";
  const action = params.get("action") ?? "";
  const sort = params.get("sort") ?? "oldest";
  const filtered = Boolean(location_id || action);
  // /locations already returns only the outlets in the caller's scope.
  const locations = useApi(() => api.locations(), []);
  const { data, error, loading, reload } = useApi(
    () => api.approvals(200, { location_id, action, sort }),
    [location_id, action, sort],
  );
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value && !(key === "sort" && value === "oldest")) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  // HQ sees every outlet, so the outlet column matters most there; show it whenever the API sends it.
  const showOutlet = (data ?? []).some((p) => p.location_name);

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Remedies the system proposed. Nothing is paid or sent until"
        highlight="a person decides"
        actions={
          <Button type="button" variant="quiet" onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3" role="group" aria-label="Filter approvals">
        <label className="text-sm text-muted-foreground">
          <span className="mr-2">Outlet</span>
          <select className={SELECT} value={location_id} onChange={(e) => setFilter("location_id", e.target.value)}>
            <option value="">All outlets</option>
            {(locations.data ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-muted-foreground">
          <span className="mr-2">Action</span>
          <select className={SELECT} value={action} onChange={(e) => setFilter("action", e.target.value)}>
            <option value="">All actions</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {humanize(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-muted-foreground">
          <span className="mr-2">Sort</span>
          <select className={SELECT} value={sort} onChange={(e) => setFilter("sort", e.target.value)}>
            {SORTS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loading ? (
        <Loading label="Loading approvals…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        filtered ? (
          <EmptyState title="No approvals match these filters">Try a different outlet or action, or clear the filters.</EmptyState>
        ) : (
          <EmptyState title="Nothing to approve">You're all caught up. New proposals appear here as customers report problems.</EmptyState>
        )
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
                        <div className="text-sm font-medium text-foreground">{categoryLabel(p.category)}</div>
                        <div className="font-mono text-xs text-muted-foreground">{p.order_ref ?? "n/a"}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <RiskBadge risk={p.risk} />
                        <FlagBadge p={p} />
                      </div>
                    </div>
                    <div className="mt-3 flex items-end justify-between">
                      <span className="text-xs text-muted-foreground">
                        {p.location_name ? `${p.location_name} · ` : ""}
                        {age(p.created_at)}
                      </span>
                      <span className={`${numClass} font-medium text-foreground`}>
                        {humanize(p.action)} {formatPaise(p.amount_paise)}
                      </span>
                    </div>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
          {/* Desktop: table */}
          <div className={`${tableWrapClass} hidden md:block`}>
            <table className={tableClass}>
              <thead>
                <tr>
                  <th scope="col" className={thClass}>Category</th>
                  <th scope="col" className={thClass}>Order</th>
                  {showOutlet && <th scope="col" className={thClass}>Outlet</th>}
                  <th scope="col" className={thClass}>Action</th>
                  <th scope="col" className={`${thClass} text-right`}>Amount</th>
                  <th scope="col" className={thClass}>Risk</th>
                  <th scope="col" className={thClass}>Age</th>
                  <th scope="col" className={thClass}><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.proposal_id} className="hover:bg-muted">
                    <td className={`${tdClass} font-medium`}>
                      {categoryLabel(p.category)}
                      <FlagBadge p={p} className="ml-2" />
                    </td>
                    <td className={`${tdClass} font-mono text-xs text-muted-foreground`}>{p.order_ref ?? "n/a"}</td>
                    {showOutlet && <td className={tdClass}>{p.location_name ?? "n/a"}</td>}
                    <td className={tdClass}>{humanize(p.action)}</td>
                    <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(p.amount_paise)}</td>
                    <td className={tdClass}><RiskBadge risk={p.risk} /></td>
                    <td className={`${tdClass} text-muted-foreground`}>{age(p.created_at)}</td>
                    <td className={`${tdClass} text-right`}>
                      <Link to={`/approvals/${p.proposal_id}`} className="font-medium text-foreground underline underline-offset-2 hover:text-brand">
                        Review<span className="sr-only"> {categoryLabel(p.category)} on {p.order_ref}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
