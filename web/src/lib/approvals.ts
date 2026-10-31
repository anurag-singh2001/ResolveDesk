import type { PendingApproval } from "../api/types";

export interface ApprovalFlag {
  tone: "warning" | "danger";
  label: string;
}

/** A voucher worth more than the order it is for (priced before the order total was checked). */
export function voucherAboveOrder(p: Pick<PendingApproval, "action" | "amount_paise" | "order_total_paise">): boolean {
  return (
    p.action === "free_item_voucher" &&
    typeof p.amount_paise === "number" &&
    typeof p.order_total_paise === "number" &&
    p.amount_paise > p.order_total_paise
  );
}

/** What the approvals list shows when a proposal cannot simply be approved. A repeat claimant is
 *  a "needs a person" signal (yellow), not a broken proposal (red). */
export function approvalFlag(p: PendingApproval): ApprovalFlag | null {
  if (p.eligible && !voucherAboveOrder(p)) return null;
  if (voucherAboveOrder(p)) return { tone: "danger", label: "Over the order total" };
  const failed = Object.entries(p.checks ?? {}).filter(([k, v]) => v === false && !k.startsWith("needs_"));
  if (failed.length > 0 && failed.every(([k]) => k === "fair_use_ok")) {
    return { tone: "warning", label: "Needs a person" };
  }
  return { tone: "danger", label: "Checks failed" };
}
