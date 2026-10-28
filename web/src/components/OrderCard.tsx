import { useApi } from "../lib/useApi";
import { api } from "../api/endpoints";
import type { CustomerMessage } from "../api/types";
import { Card, Dl, ErrorState, Loading, cx } from "./ui";
import { formatDateTime } from "../lib/format";
import { formatPaise } from "../lib/money";

/** The order behind a case: items ordered vs received, total, times, outlet and brand.
 * Uses GET /orders/{id}, which is already scoped to what the caller may see. */
export function OrderCard({ orderId }: { orderId: string }) {
  const { data: o, error, loading, reload } = useApi(() => api.order(orderId), [orderId]);

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">Order</h2>
      </div>
      {loading ? (
        <Loading label="Loading order…" />
      ) : error || !o ? (
        <div className="p-4">
          <ErrorState error={error} onRetry={reload} />
        </div>
      ) : (
        <>
          <div className="p-4">
            <Dl
              items={[
                ["Brand", o.brand_name],
                ["Outlet", o.location_name],
                ["Placed", formatDateTime(o.placed_at)],
                ["Promised by", formatDateTime(o.promised_at)],
                ["Delivered", formatDateTime(o.completed_at)],
              ]}
            />
          </div>
          {o.items.length === 0 ? (
            <p className="px-4 pb-4 text-sm text-slate-500">No items on this order.</p>
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
        </>
      )}
    </Card>
  );
}

/** What the customer wrote, in order. Kept visually apart from our template status text. */
export function CustomerMessages({ messages, own }: { messages: CustomerMessage[]; own: boolean }) {
  if (messages.length === 0) return null;
  return (
    <Card className="p-4 sm:p-6">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">{own ? "You wrote" : "Customer said"}</h2>
      <ul className="space-y-3">
        {messages.map((m, i) => (
          <li key={`${m.at}-${i}`} className="rounded-lg border border-slate-200 px-3 py-2">
            <time dateTime={m.at} className="text-xs text-slate-500">
              {formatDateTime(m.at)}
            </time>
            <blockquote className="mt-0.5 whitespace-pre-wrap text-sm text-slate-800">{m.text}</blockquote>
          </li>
        ))}
      </ul>
    </Card>
  );
}
