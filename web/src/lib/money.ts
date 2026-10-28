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

<<<<<<< HEAD
/** "180.50" -> 18050. Integer maths on the digits (no float), at most two decimals; null if invalid. */
=======
/** "120", "120.5" or "120.50" → integer paise, with integer maths only. Anything else (empty,
 *  a third decimal, a sign, an exponent) is null. The server still checks the amount. */
>>>>>>> dd4c5ed (S7.5: staff categorise a case and propose a remedy through the normal proposal path)
export function parseRupeesToPaise(text: string): number | null {
  const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
}
