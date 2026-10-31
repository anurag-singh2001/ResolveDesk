import { EmptyState, ErrorState, Loading, PageHeader, tableClass, tableWrapClass, tdClass, thClass, numClass, cx } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";
import { useApi } from "../lib/useApi";
import { Section, Tile, TileGrid, sum } from "./parts";
import { usePlatform } from "./session";
import type { JobRunRow } from "./types";

const STATUSES = ["ok", "failed", "skipped", "running"] as const;

export function JobsPage() {
  const { get } = usePlatform();
  const { data, error, loading, reload } = useApi(() => get<JobRunRow[]>("/jobs"), [get]);

  const groups = new Map<string, JobRunRow[]>();
  for (const r of data ?? []) {
    const key = `${r.tenant_slug}|${r.job}`;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const count = (rows: JobRunRow[], s: string) => sum(rows.filter((r) => r.status === s), (r) => r.run_count);

  return (
    <>
      <PageHeader title="Scheduled jobs" subtitle="Recorded runs of the background jobs, summed by business and job. Run history only; this page cannot start or stop a job." />
      {loading && <Loading />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void reload()} /> : null}
      {data && data.length === 0 && <EmptyState title="No job runs recorded">Nothing has run yet, or recording is off.</EmptyState>}
      {data && data.length > 0 && (
        <>
          <TileGrid>
            <Tile label="Runs" value={sum(data, (r) => r.run_count)} />
            <Tile label="Succeeded" value={count(data, "ok")} />
            <Tile label="Failed" value={count(data, "failed")} />
            <Tile label="Skipped" value={count(data, "skipped")} />
          </TileGrid>
          <Section title="Runs by job">
            <div className={tableWrapClass}>
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={thClass}>Business</th>
                    <th className={thClass}>Job</th>
                    {STATUSES.map((s) => (
                      <th key={s} className={cx(thClass, "text-right")}>{humanize(s)}</th>
                    ))}
                    <th className={cx(thClass, "text-right")}>Average time</th>
                    <th className={thClass}>Last started</th>
                  </tr>
                </thead>
                <tbody>
                  {[...groups.entries()].map(([key, rows]) => {
                    const finished = sum(rows, (r) => r.finished_count);
                    const ms = finished > 0 ? Math.floor(sum(rows, (r) => r.duration_ms_total) / finished) : null;
                    const last = rows.map((r) => r.last_started_at).filter((x): x is string => !!x).sort().pop() ?? null;
                    return (
                      <tr key={key}>
                        <td className={cx(tdClass, "font-mono")}>{rows[0].tenant_slug}</td>
                        <td className={tdClass}>{humanize(rows[0].job)}</td>
                        {STATUSES.map((s) => (
                          <td key={s} className={cx(tdClass, numClass, "text-right")}>{count(rows, s)}</td>
                        ))}
                        <td className={cx(tdClass, numClass, "text-right")}>{ms === null ? "n/a" : `${ms} ms`}</td>
                        <td className={tdClass}>{formatDateTime(last)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </>
  );
}
