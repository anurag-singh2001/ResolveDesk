import { Link, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { OrderStatusBadge } from "../components/badges";
import { Card, Dl, ErrorState, Loading, PageHeader, cx, numClass, tableClass, tdClass, thClass } from "../components/ui";
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
      <Link to="/orders" className="mb-4 inline-flex text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground">
        ← My orders
      </Link>
      <PageHeader
        title={`Order ${o.external_ref}`}
        subtitle={placeLine(o) || undefined}
        actions={
          me?.role === "customer" ? (
            <Link
              to={`/orders/${o.id}/report`}
              className="btn-asym inline-flex h-9 items-center gap-2 bg-neutral-900 px-4 text-sm font-medium text-white transition-colors duration-200 hover:bg-black/90 dark:bg-white dark:text-black dark:hover:bg-neutral-200"
            >
              Report a problem
            </Link>
          ) : undefined
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          <div className="border-b border-border px-4 py-3">
            <h2 className="font-montserrat text-sm font-semibold text-foreground">Items</h2>
          </div>
          {o.items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">No items on this order.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th scope="col" className={thClass}>Item</th>
                    <th scope="col" className={`${thClass} text-right`}>Ordered</th>
                    <th scope="col" className={`${thClass} text-right`}>Received</th>
                    <th scope="col" className={`${thClass} text-right`}>Price</th>
                  </tr>
                </thead>
                <tbody>
                  {o.items.map((it) => {
                    const short = it.quantity_fulfilled < it.quantity;
                    return (
                      <tr key={it.sku}>
                        <td className={tdClass}>{it.name}</td>
                        <td className={`${tdClass} ${numClass} text-right`}>{it.quantity}</td>
                        <td className={cx(tdClass, numClass, "text-right", short && "font-semibold text-red-700 dark:text-red-400")}>
                          {it.quantity_fulfilled}
                          {short && <span className="sr-only"> (fewer than ordered)</span>}
                        </td>
                        <td className={`${tdClass} ${numClass} text-right`}>{formatPaise(it.total_paise)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} className="px-4 py-3 text-right font-medium text-muted-foreground">Total</td>
                    <td className={`px-4 py-3 text-right font-semibold ${numClass}`}>{formatPaise(o.total_paise)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="mb-4 font-montserrat text-sm font-semibold text-foreground">Details</h2>
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
