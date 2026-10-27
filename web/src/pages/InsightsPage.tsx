import { api } from "../api/endpoints";
import { Button, EmptyState, ErrorState, Loading, PageHeader, numClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

/** Basis points → "12.5%" with integer maths. */
function percentFromBp(bp: number | null): string {
  if (bp === null) return "n/a";
  return `${Math.floor(bp / 100)}.${String(bp % 100).padStart(2, "0").slice(0, 1)}%`;
}

function minutes(m: number | null): string {
  return m === null ? "n/a" : `${m} min`;
}

export function InsightsPage() {
  const { data, error, loading, reload } = useApi(() => api.outletInsights(), []);

  return (
    <>
      <PageHeader
        title="Insights"
        subtitle="How each outlet in your scope did over the last 30 days. Read-only."
        actions={
          <Button type="button" variant="quiet" onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />
      {loading ? (
        <Loading label="Loading insights…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No outlets in your scope">Outlets you are responsible for appear here.</EmptyState>
      ) : (
        <div className={tableWrapClass}>
          <table className={tableClass}>
            <caption className="sr-only">Outlet metrics, last 30 days</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Outlet</th>
                <th scope="col" className={`${thClass} text-right`}>Cases opened</th>
                <th scope="col" className={`${thClass} text-right`}>Refunds confirmed</th>
                <th scope="col" className={`${thClass} text-right`}>Refund total</th>
                <th scope="col" className={`${thClass} text-right`}>Vouchers issued</th>
                <th scope="col" className={`${thClass} text-right`}>Voucher total</th>
                <th scope="col" className={`${thClass} text-right`}>Median time to decision</th>
                <th scope="col" className={`${thClass} text-right`}>Repeat customers</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.location_id} className="hover:bg-muted">
                  <th scope="row" className={`${tdClass} text-left font-medium`}>{r.name}</th>
                  <td className={`${tdClass} ${numClass} text-right`}>{r.cases_opened}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{r.refunds_confirmed_count}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(r.refunds_confirmed_paise)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{r.vouchers_issued_count}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(r.vouchers_issued_paise)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>{minutes(r.median_decision_minutes)}</td>
                  <td className={`${tdClass} ${numClass} text-right`}>
                    {percentFromBp(r.repeat_rate_bp)}
                    <span className="block text-xs text-muted-foreground">of {r.orders} orders</span>
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
