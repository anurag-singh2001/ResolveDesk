import { api } from "../api/endpoints";
import { Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

/** Basis points → "12.5%" with integer maths. */
function percentFromBp(bp: number | null): string {
  if (bp === null) return "—";
  return `${Math.floor(bp / 100)}.${String(bp % 100).padStart(2, "0").slice(0, 1)}%`;
}

function minutes(m: number | null): string {
  return m === null ? "—" : `${m} min`;
}

export function InsightsPage() {
  const { data, error, loading, reload } = useApi(() => api.outletInsights(), []);

  return (
    <>
      <PageHeader
        title="Insights"
        subtitle="How each outlet in your scope did over the last 30 days. Read-only."
        actions={
          <button type="button" onClick={() => void reload()} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Refresh
          </button>
        }
      />
      {loading ? (
        <Loading label="Loading insights…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No outlets in your scope">Outlets you are responsible for appear here.</EmptyState>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Outlet metrics, last 30 days</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Outlet</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Cases opened</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Refunds confirmed</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Refund total</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Vouchers issued</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Voucher total</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Median time to decision</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Repeat customers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((r) => (
                <tr key={r.location_id} className="hover:bg-slate-50">
                  <th scope="row" className="px-4 py-3 text-left font-medium text-slate-900">{r.name}</th>
                  <td className="px-4 py-3 text-right tabular-nums">{r.cases_opened}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.refunds_confirmed_count}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatPaise(r.refunds_confirmed_paise)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.vouchers_issued_count}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatPaise(r.vouchers_issued_paise)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{minutes(r.median_decision_minutes)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {percentFromBp(r.repeat_rate_bp)}
                    <span className="block text-xs text-slate-500">of {r.orders} orders</span>
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
