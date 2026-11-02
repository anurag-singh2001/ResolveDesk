import { useApi } from "../lib/useApi";
import { api } from "../api/endpoints";
import type { CustomerMessage, Language } from "../api/types";
import { Card, Dl, ErrorState, Loading, cx, numClass, tableClass, tdClass, thClass } from "./ui";
import { formatDateTime } from "../lib/format";
import { formatPaise } from "../lib/money";

/** The order behind a case: items ordered vs received, total, times, outlet and brand.
 * Uses GET /orders/{id}, which is already scoped to what the caller may see. */
const LABELS = {
  en: { order: "Order", brand: "Brand", outlet: "Outlet", placed: "Placed", promised: "Promised by", delivered: "Delivered", none: "No items on this order.", item: "Item", ordered: "Ordered", received: "Received", price: "Price" },
  "hi-Latn": { order: "Order", brand: "Brand", outlet: "Outlet", placed: "Order kiya", promised: "Vaada kiya gaya samay", delivered: "Pahuncha", none: "Is order mein koi item nahin.", item: "Item", ordered: "Order kiya", received: "Mila", price: "Keemat" },
  hi: { order: "ऑर्डर", brand: "ब्रांड", outlet: "आउटलेट", placed: "ऑर्डर किया", promised: "वादा किया गया समय", delivered: "पहुँचा", none: "इस ऑर्डर में कोई आइटम नहीं।", item: "आइटम", ordered: "ऑर्डर किया", received: "मिला", price: "क़ीमत" },
};

export function OrderCard({ orderId, language = "en" }: { orderId: string; language?: Language }) {
  const L = LABELS[language] ?? LABELS.en;
  const { data: o, error, loading, reload } = useApi(() => api.order(orderId), [orderId]);

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h2 className="font-montserrat text-sm font-semibold text-foreground">{L.order}</h2>
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
                [L.brand, o.brand_name],
                [L.outlet, o.location_name],
                [L.placed, formatDateTime(o.placed_at)],
                [L.promised, formatDateTime(o.promised_at)],
                [L.delivered, formatDateTime(o.completed_at)],
              ]}
            />
          </div>
          {o.items.length === 0 ? (
            <p className="px-4 pb-4 text-sm text-muted-foreground">{L.none}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th scope="col" className={thClass}>{L.item}</th>
                    <th scope="col" className={`${thClass} text-right`}>{L.ordered}</th>
                    <th scope="col" className={`${thClass} text-right`}>{L.received}</th>
                    <th scope="col" className={`${thClass} text-right`}>{L.price}</th>
                  </tr>
                </thead>
                <tbody>
                  {o.items.map((it) => {
                    const short = it.quantity_fulfilled < it.quantity;
                    return (
                      <tr key={it.sku}>
                        <td className={tdClass}>{it.name}</td>
                        <td className={cx(tdClass, "text-right", numClass)}>{it.quantity}</td>
                        <td className={cx(tdClass, "text-right", numClass, short && "font-semibold text-red-700 dark:text-red-400")}>
                          {it.quantity_fulfilled}
                          {short && <span className="sr-only"> (fewer than ordered)</span>}
                        </td>
                        <td className={cx(tdClass, "text-right", numClass)}>{formatPaise(it.total_paise)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} className={cx(tdClass, "border-b-0 text-right font-medium text-muted-foreground")}>Total</td>
                    <td className={cx(tdClass, "border-b-0 text-right font-semibold", numClass)}>{formatPaise(o.total_paise)}</td>
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
      <h2 className="mb-3 font-montserrat text-sm font-semibold text-foreground">{own ? "You wrote" : "Customer said"}</h2>
      <ul className="space-y-3">
        {messages.map((m, i) => (
          <li key={`${m.at}-${i}`} className="rounded-lg border border-border px-3 py-2">
            <time dateTime={m.at} className="text-xs text-muted-foreground">
              {formatDateTime(m.at)}
            </time>
            <blockquote className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">{m.text}</blockquote>
          </li>
        ))}
      </ul>
    </Card>
  );
}
