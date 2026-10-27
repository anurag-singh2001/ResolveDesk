import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import type { Order } from "../api/types";
import { OrderStatusBadge } from "../components/badges";
import { Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

export function placeLine(o: Pick<Order, "brand_name" | "location_name">): string {
  return [o.brand_name, o.location_name].filter(Boolean).join(" · ");
}

export function OrdersPage() {
  const { data, error, loading, reload } = useApi(() => api.orders(50), []);

  return (
    <>
      <PageHeader title="My orders" subtitle="Pick an order to see what was delivered, or"
        highlight="report a problem in one step" />
      {loading ? (
        <Loading label="Loading your orders…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No orders yet">When you place an order it will show up here.</EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((o) => (
            <li key={o.id}>
              <Link
                to={`/orders/${o.id}`}
                className="block rounded-xl"
              >
                <Card className="h-full p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="font-mono text-sm font-medium text-foreground">{o.external_ref}</div>
                      <div className="mt-0.5 truncate text-sm text-muted-foreground">{placeLine(o) || "Order"}</div>
                    </div>
                    <OrderStatusBadge status={o.status} />
                  </div>
                  <div className="mt-4 flex items-end justify-between">
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">{formatDateTime(o.placed_at)}</span>
                    <span className="font-mono text-base tabular-nums text-foreground">{formatPaise(o.total_paise)}</span>
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
