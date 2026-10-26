import { request } from "./client";
import type {
  AuditEvent,
  ChaosSettings,
  ChaosState,
  ClockState,
  Business,
  Case,
  Categories,
  DecisionResponse,
  DemoAccount,
  LoginResponse,
  Me,
  Order,
  OrderDetail,
  PendingApproval,
  SweepReport,
  TimelineEntry,
} from "./types";

const enc = encodeURIComponent;

export const api = {
  // Dev panel (APP_ENV dev/test only; 404 elsewhere).
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
  categories: () => request<Categories>("/meta/categories"),
  orders: (limit = 50) => request<Order[]>(`/orders?limit=${limit}`),
  order: (id: string) => request<OrderDetail>(`/orders/${enc(id)}`),
  cases: (limit = 100) => request<Case[]>(`/cases?limit=${limit}`),
  case: (id: string) => request<Case>(`/cases/${enc(id)}`),
  createCase: (body: { transaction_id: string; category: string | null; message: string }) =>
    request<Case>("/cases", { method: "POST", body }),
  timeline: (id: string) => request<TimelineEntry[]>(`/cases/${enc(id)}/timeline`),
  events: (id: string) => request<AuditEvent[]>(`/cases/${enc(id)}/events`),
  approvals: (limit = 200) => request<PendingApproval[]>(`/approvals?limit=${limit}`),
  decide: (proposalId: string, decision: "approved" | "rejected", note: string | null) =>
    request<DecisionResponse>(`/approvals/${enc(proposalId)}/decision`, {
      method: "POST",
      body: { decision, note },
    }),
};
