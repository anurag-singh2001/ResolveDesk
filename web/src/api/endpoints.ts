import { request } from "./client";
import type {
  ReadableExport,
  AuditEvent,
  ChaosSettings,
  ChaosState,
  ClockState,
  Business,
  Campaign,
  Case,
  GrowthSignal,
  LocationRef,
  RerunAiResult,
  OutletInsight,
  Categories,
  Alternatives,
  AskResult,
  AskSuggestion,
  CustomerOffer,
  DecisionResponse,
  SwitchResponse,
  DemoAccount,
  LoginResponse,
  Me,
  Order,
  OrderDetail,
  PendingApproval,
  QueueItem,
  StaffRemedyOptions,
  ProposedRemedy,
  PrivacyContact,
  PrivacyDryRun,
  PrivacyQueue,
  PolicyDoc,
  RulesSummary,
  PolicySectionDetail,
  SweepReport,
  Consents,
  DataHeld,
  ErasureInfo,
  ErasureRequest,
  TimelineEntry,
  Language,
  Preferences,
  ReplyTemplates,
  RemedyOptions,
} from "./types";

const enc = encodeURIComponent;

export interface ApprovalFilters {
  location_id?: string;
  action?: string;
  sort?: string;
}

export interface QueueFilters {
  reason?: string;
  category?: string;
  owned_by_me?: boolean;
}

export const api = {
  // Demo controls (APP_ENV dev/test only; 404 elsewhere).
  chaos: () => request<ChaosState>("/admin/chaos"),
  setChaos: (service: string, settings: Partial<ChaosSettings>) =>
    request<ChaosState>("/admin/chaos", { method: "POST", body: { service, ...settings } }),
  sweep: () => request<SweepReport>("/admin/sweep", { method: "POST" }),
  clock: () => request<ClockState>("/admin/clock"),
  advanceClock: (advance_seconds: number) =>
    request<ClockState>("/admin/clock", { method: "POST", body: { advance_seconds } }),
  resetClock: () => request<ClockState>("/admin/clock", { method: "POST", body: { reset: true } }),
  businesses: () => request<Business[]>("/auth/businesses", { anonymous: true }),
  demoAccounts: () => request<DemoAccount[]>("/auth/demo-accounts", { anonymous: true }),
  login: (tenant: string, email: string, password: string) =>
    request<LoginResponse>("/auth/login", {
      method: "POST",
      body: { tenant, email, password },
      anonymous: true,
    }),
  me: () => request<Me>("/me"),
  myConsents: () => request<Consents>("/me/consents"),
  setConsent: (purpose: string, granted: boolean) =>
    request<Consents>(`/me/consents/${enc(purpose)}`, { method: "POST", body: { granted } }),
  dataHeld: () => request<DataHeld>("/me/data-held"),
  dataExport: () => request<unknown>("/me/data-export"),
  readableExport: () => request<ReadableExport>("/me/data-export/readable"),
  myErasureRequest: () => request<ErasureRequest | null>("/me/erasure-request"),
  requestErasure: (notifyVia?: "phone" | "email") =>
    request<ErasureRequest>("/me/erasure-request", { method: "POST", body: notifyVia ? { notify_via: notifyVia } : {} }),
  erasureInfo: () => request<ErasureInfo>("/me/erasure-info"),
  privacyQueue: () => request<PrivacyQueue>("/data-requests/queue"),
  privacyDryRun: (id: string) => request<PrivacyDryRun>(`/data-requests/${enc(id)}/dry-run`),
  approveErasure: (id: string, d: PrivacyDryRun) =>
    request<unknown>(`/data-requests/${enc(id)}/approve`, {
      method: "POST",
      body: { payload_hash: d.payload_hash, approval_token: d.approval_token },
    }),
  withdrawErasure: () => request<ErasureRequest>("/me/erasure-request/cancel", { method: "POST" }),
  categories: () => request<Categories>("/meta/categories"),
  preferences: () => request<Preferences>("/me/preferences"),
  setPreferences: (language: Language) =>
    request<Preferences>("/me/preferences", { method: "PUT", body: { language } }),
  policies: () => request<PolicyDoc[]>("/policies"),
  rulesSummary: () => request<RulesSummary>("/policies/rules-summary"),
  policySection: (docKey: string, section: string) =>
    request<PolicySectionDetail>(`/policies/${enc(docKey)}/${enc(section)}`),
  privacyContact: () => request<PrivacyContact>("/meta/privacy"),
  orders: (limit = 50) => request<Order[]>(`/orders?limit=${limit}`),
  order: (id: string) => request<OrderDetail>(`/orders/${enc(id)}`),
  cases: (limit = 100) => request<Case[]>(`/cases?limit=${limit}`),
  case: (id: string) => request<Case>(`/cases/${enc(id)}`),
  replyTemplates: (id: string) => request<ReplyTemplates>(`/cases/${enc(id)}/reply-templates`),
  staffReply: (id: string, body: { template_id: string; note?: string; idempotency_key: string }) =>
    request<{ sent: boolean }>(`/cases/${enc(id)}/staff-reply`, { method: "POST", body }),
  closeCase: (id: string, reason: string) =>
    request<{ case_id: string; status: string; close_reason: string }>(`/cases/${enc(id)}/close`, {
      method: "POST",
      body: { reason },
    }),
  orderRemedyOptions: (orderId: string, category: string) =>
    request<RemedyOptions>(`/orders/${enc(orderId)}/remedy-options?category=${enc(category)}`),
  caseRemedyOptions: (id: string) => request<RemedyOptions>(`/cases/${enc(id)}/remedy-options`),
  setRemedyChoice: (id: string, option: string) =>
    request<Case>(`/cases/${enc(id)}/remedy-choice`, { method: "PUT", body: { option } }),
  createCase: (body: { transaction_id: string; category: string | null; message: string; remedy_choice?: string | null }) =>
    request<Case>("/cases", { method: "POST", body }),
  replyToCase: (id: string, message: string) =>
    request<Case>(`/cases/${enc(id)}/messages`, { method: "POST", body: { message } }),
  rerunAi: (id: string) => request<RerunAiResult>(`/cases/${enc(id)}/rerun-ai`, { method: "POST" }),
  timeline: (id: string) => request<TimelineEntry[]>(`/cases/${enc(id)}/timeline`),
  events: (id: string) => request<AuditEvent[]>(`/cases/${enc(id)}/events`),
  staffRemedyOptions: (id: string) =>
    request<StaffRemedyOptions>(`/cases/${enc(id)}/staff-remedy-options`),
  categorise: (id: string, category: string) =>
    request<StaffRemedyOptions>(`/cases/${enc(id)}/categorise`, { method: "POST", body: { category } }),
  proposeRemedy: (id: string, action: string, amount_paise: number) =>
    request<ProposedRemedy>(`/cases/${enc(id)}/propose`, { method: "POST", body: { action, amount_paise } }),
  approvals: (limit = 200, filters: ApprovalFilters = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (filters.location_id) q.set("location_id", filters.location_id);
    if (filters.action) q.set("action", filters.action);
    if (filters.sort && filters.sort !== "oldest") q.set("sort", filters.sort);
    return request<PendingApproval[]>(`/approvals?${q.toString()}`);
  },
  caseQueue: (filters: QueueFilters = {}) => {
    const q = new URLSearchParams();
    if (filters.reason) q.set("reason", filters.reason);
    if (filters.category) q.set("category", filters.category);
    if (filters.owned_by_me) q.set("owned_by_me", "true");
    const qs = q.toString();
    return request<QueueItem[]>(`/cases/queue${qs ? `?${qs}` : ""}`);
  },
  locations: () => request<LocationRef[]>("/locations"),
  outletInsights: () => request<OutletInsight[]>("/insights/outlets"),
  growthSignals: () => request<GrowthSignal[]>("/growth/signals"),
  refreshSignals: () => request<GrowthSignal[]>("/growth/signals/refresh", { method: "POST" }),
  proposeCampaign: (signalId: string) =>
    request<Campaign>(`/growth/signals/${enc(signalId)}/campaign`, { method: "POST", body: {} }),
  campaign: (id: string) => request<Campaign>(`/growth/campaigns/${enc(id)}`),
  decideCampaign: (id: string, decision: "approved" | "rejected") =>
    request<Campaign>(`/growth/campaigns/${enc(id)}/approve`, { method: "POST", body: { decision } }),
  campaignVerdict: (id: string) => request<Campaign>(`/growth/campaigns/${enc(id)}/verdict`, { method: "POST" }),
  alternatives: (proposalId: string) => request<Alternatives>(`/approvals/${enc(proposalId)}/alternatives`),
  switchRemedy: (proposalId: string, body: { action: string; amount_paise: number; approve: boolean; note: string; self_approve_reason?: string }) =>
    request<SwitchResponse>(`/approvals/${enc(proposalId)}/switch`, { method: "POST", body }),
  askSuggestion: (proposalId: string) => request<AskSuggestion>(`/approvals/${enc(proposalId)}/ask-customer`),
  askCustomer: (proposalId: string, options: { action: string; amount_paise: number }[]) =>
    request<AskResult>(`/approvals/${enc(proposalId)}/ask-customer`, { method: "POST", body: { options } }),
  caseOffer: (id: string) => request<CustomerOffer>(`/cases/${enc(id)}/offer`),
  chooseOffer: (id: string, option: string) =>
    request<CustomerOffer>(`/cases/${enc(id)}/offer-choice`, { method: "PUT", body: { option } }),
  decide: (proposalId: string, decision: "approved" | "rejected", note: string | null) =>
    request<DecisionResponse>(`/approvals/${enc(proposalId)}/decision`, {
      method: "POST",
      body: { decision, note },
    }),
};
