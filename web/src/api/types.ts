// Shapes from docs/api/frontend-contract.md. Fields marked NEW there are optional here so the
// app keeps working against a backend that doesn't send them yet.

export type Role = "customer" | "location_manager" | "franchisee_owner" | "hq_owner";

export interface ChaosSettings {
  timeout_rate: number;
  transient_error_rate: number;
  accept_then_timeout_rate: number;
  error_rate: number;
  processing_rate: number;
  settle_after_polls: number;
  delay_ms: number;
  seed: number;
}

export type ChaosState = Record<string, ChaosSettings>;

export interface SweepReport {
  executed: string[];
  reconciled: string[];
  escalated_cases: string[];
  verified: string[];
  pruned_threads: number;
  events_published: number;
}

export interface Business {
  slug: string;
  name: string;
  vertical: string;
}

export interface DemoAccount {
  tenant: string;
  email: string;
  name: string;
  role: Role;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at?: string; // NEW
}

export interface Me {
  user_id: string;
  name: string;
  email: string;
  role: Role;
  location_ids: string[];
  brand_ids: string[];
  tenant?: Business; // NEW
  growth_enabled?: boolean; // NEW: the tenant's growth flag
}

export interface Categories {
  categories: string[];
  free_text: boolean;
}

/** The customer's own choice of language for messages we send them (S5.6). */
export type Language = "en" | "hi-Latn" | "hi";

export interface Preferences {
  language: Language;
}

export interface PrivacyContact {
  name: string;
  email: string;
}

export interface Order {
  id: string;
  external_ref: string;
  brand_id: string | null;
  location_id: string | null;
  brand_name?: string | null; // NEW
  location_name?: string | null; // NEW
  placed_at: string;
  total_paise: number;
  status: string;
}

export interface OrderItem {
  sku: string;
  name: string;
  quantity: number;
  quantity_fulfilled: number;
  total_paise: number;
}

export interface OrderDetail extends Order {
  items: OrderItem[];
  promised_at: string | null;
  completed_at: string | null;
}

export type Stage =
  | "received"
  | "investigating"
  | "awaiting_info"
  | "awaiting_approval"
  | "processing"
  | "confirmed"
  | "declined"
  | "escalated"
  | "closed";

export interface CustomerMessage {
  at: string;
  text: string;
}

export interface Case {
  id: string;
  transaction_id: string | null;
  order_ref?: string | null; // NEW
  category: string | null;
  stage: Stage | string;
  message: string;
  action: string | null;
  amount_paise: number | null;
  proposal_id: string | null;
  created_at?: string | null; // NEW
  customer_messages?: CustomerMessage[]; // only on GET /cases/{id}
}

export interface TimelineEntry {
  at: string;
  stage: string;
  title: string;
  text: string;
}

export interface AuditEvent {
  occurred_at: string;
  actor_type: string;
  event: string;
  payload: Record<string, unknown>;
}

export interface Citation {
  section_ref: string;
  doc_key: string;
  version: number | string;
}

export interface PendingApproval {
  proposal_id: string;
  case_id: string;
  category: string | null;
  action: string;
  risk: "low" | "medium" | "high" | string;
  amount_paise: number | null;
  order_ref: string | null;
  order_total_paise: number | null;
  reason: string;
  checks: Record<string, boolean | number | string>; // pass/fail booleans plus values (amounts, counts) and needs_* flags
  eligible: boolean;
  errors: string[];
  created_at?: string | null; // NEW
  customer_messages?: CustomerMessage[]; // only on GET /cases/{id}
  customer_message?: string | null; // NEW
  location_name?: string | null; // NEW
  citations?: Citation[]; // NEW
}

export interface OutletInsight {
  location_id: string;
  name: string;
  cases_opened: number;
  refunds_confirmed_count: number;
  refunds_confirmed_paise: number;
  vouchers_issued_count: number;
  vouchers_issued_paise: number;
  median_decision_minutes: number | null;
  orders: number;
  repeat_rate_bp: number | null; // basis points; null with no orders
}

export interface LocationRef {
  id: string;
  slug: string;
  name: string;
}

export interface GrowthSignal {
  id: string;
  location_id: string;
  metric: string;
  baseline_bp: number;
  recent_bp: number;
  baseline_n: number;
  recent_n: number;
  drop_bp: number;
  status: string;
  diagnosis: { findings?: string[]; hypotheses?: string[] };
  diagnosis_source: string;
  recent_end: string;
  campaign_id?: string | null; // NEW: the signal's campaign, once one was proposed
}

export interface CampaignApproval {
  decided_by: string;
  role: string;
  decision: "approved" | "rejected";
  expires_at: string;
}

export interface PlaybookEntry {
  verdict: string;
  uplift_bp: number | null;
  treatment_n: number;
  holdout_n: number;
  confidence_note: string;
  lesson: string;
}

export interface Campaign {
  id: string;
  signal_id: string;
  location_id: string;
  status: string;
  payload_hash: string;
  params: Record<string, unknown>;
  budget_paise: number;
  expires_at: string;
  sent_at: string | null;
  treatment_n: number;
  holdout_n: number;
  approvals: CampaignApproval[];
  fully_approved: boolean;
  playbook: PlaybookEntry | null;
}

export interface DecisionResponse {
  proposal_id: string;
  decision: "approved" | "rejected";
  expires_at: string;
  execution: string;
}

export interface ClockState {
  now: string;
  offset_seconds: number;
}

export interface ConsentState {
  purpose: string;
  channel: string;
  granted: boolean;
  updated_at: string | null;
}

export interface ConsentEvent {
  purpose: string;
  channel: string;
  granted: boolean;
  source: string;
  notice_version: string;
  at: string;
}

export interface Consents {
  notice_version: string;
  consents: ConsentState[];
  history: ConsentEvent[];
}

export interface ErasureRequest {
  id: string;
  kind: string;
  status: "pending_approval" | "deferred" | "completed";
  reason: string | null;
  deferred_until: string | null;
  requested_at: string;
  completed_at: string | null;
}
