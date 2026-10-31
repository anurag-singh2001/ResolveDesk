// Money arrives as integer paise. Format with integer maths only (no float division), so
// ₹0.29 never shows as ₹0.28999.

const groupIN = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return "n/a";
  const p = Math.trunc(paise);
  const negative = p < 0;
  const abs = Math.abs(p);
  const rupees = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, "0");
  return `${negative ? "-" : ""}₹${groupIN.format(rupees)}.${fraction}`;
}

/** "180.50" -> 18050. Integer maths on the digits (no float), at most two decimals; null if invalid. */
export function parseRupeesToPaise(text: string): number | null {
  const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
}

/** Whole rupees for chart axes ("₹12,000"); integer maths, no paise. */
export function formatPaiseShort(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return "n/a";
  const p = Math.trunc(paise);
  return `${p < 0 ? "-" : ""}₹${groupIN.format(Math.floor(Math.abs(p) / 100))}`;
}
