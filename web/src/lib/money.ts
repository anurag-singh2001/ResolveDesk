// Money arrives as integer paise. Format with integer maths only (no float division), so
// ₹0.29 never shows as ₹0.28999.

const groupIN = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return "—";
  const p = Math.trunc(paise);
  const negative = p < 0;
  const abs = Math.abs(p);
  const rupees = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, "0");
  return `${negative ? "-" : ""}₹${groupIN.format(rupees)}.${fraction}`;
}
