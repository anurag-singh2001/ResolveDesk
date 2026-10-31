import type { ReactNode } from "react";
import { Card } from "../components/ui";
import { formatPaise } from "../lib/money";

/** A metric tile: a label and one number. Numbers are mono. */
export function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-2xl font-medium tabular-nums text-foreground">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function TileGrid({ children }: { children: ReactNode }) {
  return <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>;
}

export function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-xl font-medium text-foreground">{title}</h2>
      {note ? <p className="mb-3 mt-1 text-sm text-muted-foreground">{note}</p> : <div className="mb-3" />}
      {children}
    </section>
  );
}

/** Whole paise from micro-paise, integer maths only. Labelled an estimate wherever it shows. */
export function microToRupees(micro: number): string {
  return formatPaise(Math.floor(micro / 1_000_000));
}

/** A ratio as a percentage with one decimal, from integers (display only). */
export function pct(part: number, whole: number): string {
  if (whole <= 0) return "n/a";
  const tenths = Math.floor((part * 1000) / whole);
  return `${Math.floor(tenths / 10)}.${tenths % 10}%`;
}

export function sum<T>(rows: T[], pick: (r: T) => number): number {
  return rows.reduce((a, r) => a + pick(r), 0);
}
