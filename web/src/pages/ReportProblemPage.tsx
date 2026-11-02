import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import { Alert, Button, Card, ErrorState, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { RemedyChoice } from "../components/RemedyChoice";
import type { RemedyOption } from "../api/types";
import { categoryLabel } from "../lib/format";
import { formatPaise } from "../lib/money";
import { useApi } from "../lib/useApi";

const FREE_TEXT = "__free_text__";
const MAX_LEN = 2000;

export function ReportProblemPage() {
  const { orderId = "" } = useParams();
  const navigate = useNavigate();
  const order = useApi(() => api.order(orderId), [orderId]);
  const cats = useApi(() => api.categories(), []);
  const [category, setCategory] = useState("");
  const [message, setMessage] = useState("");
  const [options, setOptions] = useState<RemedyOption[]>([]);
  const [remedy, setRemedy] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Options depend on the order and the category; the server computes amounts and timing.
  useEffect(() => {
    setOptions([]);
    setRemedy("");
    if (!category || category === FREE_TEXT || !orderId) return;
    let live = true;
    api
      .orderRemedyOptions(orderId, category)
      .then((r) => {
        if (!live || !r.choice_required) return;
        setOptions(r.options);
        setRemedy(r.options[0]?.code ?? "");
      })
      .catch(() => undefined); // no choice shown; the normal flow still works
    return () => {
      live = false;
    };
  }, [orderId, category]);

  if (order.loading || cats.loading) return <Loading />;
  if (order.error || !order.data) return <ErrorState error={order.error} onRetry={order.reload} />;
  if (cats.error || !cats.data) return <ErrorState error={cats.error} onRetry={cats.reload} />;
  const o = order.data;
  const { categories, free_text } = cats.data;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!category) return setError("Choose what went wrong.");
    if (!message.trim()) return setError("Tell us what happened.");
    setSubmitting(true);
    try {
      const created = await api.createCase({
        transaction_id: o.id,
        category: category === FREE_TEXT ? null : category,
        message: message.trim(),
        remedy_choice: options.length > 1 ? remedy : null,
      });
      navigate(`/cases/${created.id}`, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <>
      <Link to={`/orders/${o.id}`} className="mb-4 inline-flex text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground">
        ← Order {o.external_ref}
      </Link>
      <PageHeader title="Report a problem" subtitle={`Order ${o.external_ref} · ${formatPaise(o.total_paise)}`} />
      <Card className="max-w-2xl p-5 sm:p-6">
        <form onSubmit={onSubmit} className="space-y-5" noValidate aria-label="Report a problem">
          {error && <Alert>{error}</Alert>}
          <Field label="What went wrong?" htmlFor="category">
            <select id="category" className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">Choose one</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {categoryLabel(c)}
                </option>
              ))}
              {free_text && <option value={FREE_TEXT}>Not sure, just describe it</option>}
            </select>
          </Field>
          <RemedyChoice options={options} value={remedy} onChange={setRemedy} />
          <Field label="Tell us what happened" htmlFor="message" hint={`${message.length}/${MAX_LEN}`}>
            <textarea
              id="message"
              rows={5}
              maxLength={MAX_LEN}
              className={inputClass}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="For example: the order arrived 40 minutes late and the fries were missing."
            />
          </Field>
          <p className="text-xs text-muted-foreground">
            We check your report against the order's records. A refund is always approved by a person, and we
            only tell you it's done once the payment is confirmed.
          </p>
          <div className="flex justify-end gap-2">
            <Link to={`/orders/${o.id}`} className="inline-flex h-8 items-center rounded-md px-2.5 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground">
              Cancel
            </Link>
            <Button type="submit" loading={submitting}>
              Submit report
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
