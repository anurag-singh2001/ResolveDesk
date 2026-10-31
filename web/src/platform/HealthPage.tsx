import { Alert, EmptyState, ErrorState, Loading, PageHeader, tableClass, tableWrapClass, tdClass, thClass, numClass, cx } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";
import { useApi } from "../lib/useApi";
import { Section, Tile, TileGrid, sum } from "./parts";
import { usePlatform } from "./session";
import type { ActivityRow, ApprovalCountRow, CaseCountRow, TenantRow } from "./types";

export function HealthPage() {
  const { get } = usePlatform();
  const { data, error, loading, reload } = useApi(async () => {
    const [tenants, cases, approvals, activity] = await Promise.all([
      get<TenantRow[]>("/tenants"),
      get<CaseCountRow[]>("/cases"),
      get<ApprovalCountRow[]>("/approvals"),
      get<ActivityRow[]>("/activity"),
    ]);
    return { tenants, cases, approvals, activity };
  }, [get]);

  return (
    <>
      <PageHeader title="Health" subtitle="Counts per business. No customer names, contact details or message text appear in the portal." />
      {loading && <Loading />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void reload()} /> : null}
      {data && (
        <>
          <TileGrid>
            <Tile label="Businesses" value={data.tenants.length} />
            <Tile label="Cases, all time" value={sum(data.cases, (r) => r.case_count)} />
            <Tile label="Approval decisions" value={sum(data.approvals, (r) => r.approval_count)} />
            <Tile label="Businesses with system activity" value={data.activity.filter((a) => a.last_system_event_at).length} />
          </TileGrid>

          <Section title="Businesses">
            {data.tenants.length === 0 ? (
              <EmptyState title="No businesses yet">Nothing is set up on this platform.</EmptyState>
            ) : (
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <th className={thClass}>Business</th>
                      <th className={thClass}>Pack</th>
                      <th className={cx(thClass, "text-right")}>Cases</th>
                      <th className={cx(thClass, "text-right")}>Approvals</th>
                      <th className={thClass}>Last system activity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tenants.map((t) => {
                      const last = data.activity.find((a) => a.tenant_slug === t.tenant_slug)?.last_system_event_at ?? null;
                      return (
                        <tr key={t.tenant_slug}>
                          <td className={cx(tdClass, "font-mono")}>{t.tenant_slug}</td>
                          <td className={tdClass}>{humanize(t.vertical_pack)}</td>
                          <td className={cx(tdClass, numClass, "text-right")}>
                            {sum(data.cases.filter((c) => c.tenant_slug === t.tenant_slug), (c) => c.case_count)}
                          </td>
                          <td className={cx(tdClass, numClass, "text-right")}>
                            {sum(data.approvals.filter((a) => a.tenant_slug === t.tenant_slug), (a) => a.approval_count)}
                          </td>
                          <td className={tdClass}>{last ? formatDateTime(last) : "No activity yet"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section title="Alerts">
            <Alert tone="info">Alerts are not built yet, so none are shown. This page does not guess at them.</Alert>
          </Section>
        </>
      )}
    </>
  );
}
