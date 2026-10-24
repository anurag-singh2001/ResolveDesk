import { Link, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { OrderStatusBadge } from "../components/badges";
import { Card, Dl, ErrorState, Loading, PageHeader, cx } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";
import { placeLine } from "./OrdersPage";

export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const { me } = useAuth();
  const { data: o, error, loading, reload } = useApi(() => api.order(orderId), [orderId]);

  if (loading) return <Loading label="Loading order…" />;
  if (error || !o) return <ErrorState error={error} onRetry={reload} />;

  return (
    <>
      <Link to="/orders" className="mb-4 inline-flex text-sm text-slate-500 hover:text-slate-900">
        ← My orders
      </Link>
      <PageHeader
        title={`Order ${o.external_ref}`}
        subtitle={placeLine(o) || undefined}
        actions={
          me?.role === "customer" ? (
            <Link
              to={`/orders/${o.id}/report`}
              className="inline-flex items-center rounded-lg bg-accent-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
            >
              Report a problem
            </Link>
          ) : undefined
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-900">Items</h2>
          </div>
          {o.items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-500">No items on this order.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">Item</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Ordered</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Received</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Price</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {o.items.map((it) => {
                    const short = it.quantity_fulfilled < it.quantity;
                    return (
                      <tr key={it.sku}>
                        <td className="px-4 py-3 text-slate-900">{it.name}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{it.quantity}</td>
                        <td className={cx("px-4 py-3 text-right tabular-nums", short && "font-semibold text-rose-700")}>
                          {it.quantity_fulfilled}
                          {short && <span className="sr-only"> (fewer than ordered)</span>}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{formatPaise(it.total_paise)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-slate-200">
                    <td colSpan={3} className="px-4 py-3 text-right font-medium text-slate-700">Total</td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">{formatPaise(o.total_paise)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="mb-4 text-sm font-semibold text-slate-900">Details</h2>
          <Dl
            items={[
              ["Status", <OrderStatusBadge key="s" status={o.status} />],
              ["Placed", formatDateTime(o.placed_at)],
              ["Promised by", formatDateTime(o.promised_at)],
              ["Delivered", formatDateTime(o.completed_at)],
            ]}
          />
        </Card>
      </div>
    </>
  );
}
