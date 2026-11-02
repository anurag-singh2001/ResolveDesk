import { EmptyState, ErrorState, Loading, PageHeader, tableClass, tableWrapClass, tdClass, thClass, numClass, cx } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";
import { useApi } from "../lib/useApi";
import { Section, Tile, TileGrid, sum } from "./parts";
import { usePlatform } from "./session";
import type { AlertRow, ErrorLogRow } from "./types";

export function LogsPage() {
  const { get } = usePlatform();
  const { data, error, loading, reload } = useApi(
    () => Promise.all([get<AlertRow[]>("/alerts"), get<ErrorLogRow[]>("/logs")]),
    [get],
  );
  const alerts = data?.[0];
  const logs = data?.[1];

  return (
    <>
      <PageHeader title="Logs and alerts" subtitle="Alerts raised by the rule checks, and error counts from the last 14 days. Scrubbed counts only: no messages and no customer data. Nothing here is sent anywhere." />
      {loading && <Loading />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void reload()} /> : null}
      {alerts && logs && (
        <>
          <TileGrid>
            <Tile label="Open alerts" value={alerts.filter((a) => a.status === "open").length} />
            <Tile label="Resolved, last 7 days" value={alerts.filter((a) => a.status !== "open").length} />
            <Tile label="Errors, last 14 days" value={sum(logs, (l) => l.occurrences)} />
          </TileGrid>
          <Section title="Alerts">
            {alerts.length === 0 ? (
              <EmptyState title="No alerts">No rule has fired in the last 7 days.</EmptyState>
            ) : (
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <th className={thClass}>Rule</th>
                      <th className={thClass}>Where</th>
                      <th className={thClass}>Status</th>
                      <th className={cx(thClass, "text-right")}>Value</th>
                      <th className={cx(thClass, "text-right")}>Limit</th>
                      <th className={thClass}>Opened</th>
                      <th className={thClass}>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a) => (
                      <tr key={`${a.rule}|${a.scope}|${a.opened_at}`}>
                        <td className={tdClass}>{humanize(a.rule)}</td>
                        <td className={cx(tdClass, "font-mono")}>{a.scope}</td>
                        <td className={tdClass}>{humanize(a.status)}</td>
                        <td className={cx(tdClass, numClass, "text-right")}>{a.value}</td>
                        <td className={cx(tdClass, numClass, "text-right")}>{a.threshold}</td>
                        <td className={tdClass}>{formatDateTime(a.opened_at)}</td>
                        <td className={tdClass}>{formatDateTime(a.last_seen_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
          <Section title="Errors">
            {logs.length === 0 ? (
              <EmptyState title="No errors recorded">Nothing has been logged in the last 14 days.</EmptyState>
            ) : (
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <th className={thClass}>Day</th>
                      <th className={thClass}>Service</th>
                      <th className={thClass}>Level</th>
                      <th className={thClass}>Event</th>
                      <th className={thClass}>Error type</th>
                      <th className={cx(thClass, "text-right")}>Count</th>
                      <th className={thClass}>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((l) => (
                      <tr key={`${l.day}|${l.service}|${l.level}|${l.event_code}|${l.error_class}`}>
                        <td className={tdClass}>{l.day}</td>
                        <td className={tdClass}>{l.service}</td>
                        <td className={tdClass}>{humanize(l.level)}</td>
                        <td className={cx(tdClass, "font-mono")}>{l.event_code}</td>
                        <td className={cx(tdClass, "font-mono")}>{l.error_class}</td>
                        <td className={cx(tdClass, numClass, "text-right")}>{l.occurrences}</td>
                        <td className={tdClass}>{formatDateTime(l.last_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </>
  );
}
