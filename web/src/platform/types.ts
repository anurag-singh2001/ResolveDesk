// Shapes of the aggregate-only platform routes. Counts, sums and labels: no ids, no text.
export interface TenantRow { tenant_slug: string; vertical_pack: string }
export interface CaseCountRow { tenant_slug: string; day: string; status: string; case_count: number }
export interface ApprovalCountRow { tenant_slug: string; day: string; decision: string; mode: string; approval_count: number }
export interface ActivityRow { tenant_slug: string; last_system_event_at: string | null }
export interface LlmUsageRow {
  tenant_slug: string; day: string; provider: string; model: string; purpose: string; outcome: string;
  run_count: number; call_count: number; failure_count: number; tokens_in: number; tokens_out: number;
  cost_micro_paise: number; latency_ms_total: number;
}
export interface AlertRow {
  rule: string; scope: string; status: string; value: number; threshold: number;
  opened_at: string; last_seen_at: string; resolved_at: string | null;
}
export interface ErrorLogRow {
  service: string; level: string; event_code: string; error_class: string; day: string;
  occurrences: number; last_at: string;
}
export interface JobRunRow {
  tenant_slug: string; day: string; job: string; status: string; run_count: number;
  finished_count: number; duration_ms_total: number; last_started_at: string | null;
}
