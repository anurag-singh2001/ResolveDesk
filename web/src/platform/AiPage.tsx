import { EmptyState, ErrorState, Loading, PageHeader, tableClass, tableWrapClass, tdClass, thClass, numClass, cx } from "../components/ui";
import { useApi } from "../lib/useApi";
import { Section, Tile, TileGrid, microToRupees, pct, sum } from "./parts";
import { usePlatform } from "./session";
import type { LlmUsageRow } from "./types";

function group(rows: LlmUsageRow[], key: (r: LlmUsageRow) => string): Array<[string, LlmUsageRow[]]> {
  const m = new Map<string, LlmUsageRow[]>();
  for (const r of rows) m.set(key(r), [...(m.get(key(r)) ?? []), r]);
  return [...m.entries()];
}

function Stats({ rows }: { rows: LlmUsageRow[] }) {
  const calls = sum(rows, (r) => r.call_count);
  const runs = sum(rows, (r) => r.run_count);
  const right = cx(tdClass, numClass, "text-right");
  return (
    <>
      <td className={right}>{calls}</td>
      <td className={right}>{sum(rows, (r) => r.tokens_in + r.tokens_out)}</td>
      <td className={right}>{microToRupees(sum(rows, (r) => r.cost_micro_paise))}</td>
      <td className={right}>{calls > 0 ? `${Math.floor(sum(rows, (r) => r.latency_ms_total) / calls)} ms` : "n/a"}</td>
      <td className={right}>{pct(sum(rows, (r) => r.failure_count), calls)}</td>
      <td className={right}>{pct(sum(rows.filter((r) => r.outcome === "fallback_used"), (r) => r.run_count), runs)}</td>
    </>
  );
}

function Head({ first }: { first: string[] }) {
  return (
    <tr>
      {first.map((h) => (
        <th key={h} className={thClass}>{h}</th>
      ))}
      {["Calls", "Tokens", "Est. cost", "Average time", "Failure rate", "Fallback rate"].map((h) => (
        <th key={h} className={cx(thClass, "text-right")}>{h}</th>
      ))}
    </tr>
  );
}

export function AiPage() {
  const { get } = usePlatform();
  const { data, error, loading, reload } = useApi(() => get<LlmUsageRow[]>("/ai-usage"), [get]);
  const calls = data ? sum(data, (r) => r.call_count) : 0;

  return (
    <>
      <PageHeader title="AI performance" subtitle="Model calls summed by business, provider and day. Cost is an estimate from the configured price table; no prompt or reply text is stored." />
      {loading && <Loading />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void reload()} /> : null}
      {data && data.length === 0 && <EmptyState title="No model calls recorded">Nothing has been recorded yet.</EmptyState>}
      {data && data.length > 0 && (
        <>
          <TileGrid>
            <Tile label="Calls" value={calls} />
            <Tile label="Tokens" value={sum(data, (r) => r.tokens_in + r.tokens_out)} />
            <Tile label="Estimated cost" value={microToRupees(sum(data, (r) => r.cost_micro_paise))} />
            <Tile label="Failure rate" value={pct(sum(data, (r) => r.failure_count), calls)} />
          </TileGrid>
          <Section title="By business and provider">
            <div className={tableWrapClass}>
              <table className={tableClass}>
                <thead><Head first={["Business", "Provider"]} /></thead>
                <tbody>
                  {group(data, (r) => `${r.tenant_slug}|${r.provider}`).map(([key, rows]) => (
                    <tr key={key}>
                      <td className={cx(tdClass, "font-mono")}>{rows[0].tenant_slug}</td>
                      <td className={tdClass}>{rows[0].provider}</td>
                      <Stats rows={rows} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section title="By day">
            <div className={tableWrapClass}>
              <table className={tableClass}>
                <thead><Head first={["Day"]} /></thead>
                <tbody>
                  {group(data, (r) => r.day).sort((a, b) => b[0].localeCompare(a[0])).map(([day, rows]) => (
                    <tr key={day}>
                      <td className={cx(tdClass, "font-mono")}>{day}</td>
                      <Stats rows={rows} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </>
  );
}
