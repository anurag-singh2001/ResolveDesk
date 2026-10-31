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

export interface PolicySection {
  id: string;
  anchor: string;
  title: string;
  text: string;
}

export interface PolicyDoc {
  id: string;
  title: string;
  topic: string;
  version: number;
  in_force_from: string;
  in_force_to: string | null;
  scope: string;
  sections: PolicySection[];
}

export interface RuleLine {
  code: string;
  kind: "voucher" | "refund" | "refund_missing" | "apology";
  text: string;
  approval: "instant" | "team" | null;
  approval_text: string | null;
  max_paise: number | null;
  percent: number | null;
  min_minutes_late: number | null;
  label: string | null;
}

export interface CategoryRule {
  category: string;
  title: string;
  options: RuleLine[];
  tiers: RuleLine[];
  notes: string[];
  decided_by: "instant" | "team" | "mixed";
  setting_keys: string[];
}

/** One setting behind the rules; only staff receive these. */
export interface RuleSetting {
  key: string;
  value: unknown;
  source: "pack_default" | "tenant_override";
}

export interface RulesSummary {
  language: Language;
  pack_name: string;
  pack_version: number;
  pack_updated: string;
  settings_updated: string | null;
  in_force_since: string;
  in_force_text: string;
  categories: CategoryRule[];
  settings: RuleSetting[];
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
  can_rerun_ai?: boolean; // staff, GET /cases/{id}: escalated because the AI was unavailable
  staff_messages?: StaffMessage[]; // GET /cases/{id}, staff only (S7.6)
  closed?: boolean;
  close_reason?: string | null;
  basis?: string[]; // which rule set the amount (S8.3)
  sources?: DecisionSource[]; // cited policy sections as links (S8.3)
}

export interface RerunAiResult {
  status: "started" | "already_running" | string;
}

export interface StaffMessage {
  at: string;
  kind: "template" | "note";
  template_id: string | null;
  text: string;
  sender_user_id: string | null;
}

export interface ReplyTemplates {
  language: string;
  templates: Array<{ id: string; label: string; preview: string }>;
  close_reasons: Array<{ id: string; label: string }>;
  note_max_length: number;
  closed: boolean;
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

/** A cited policy section resolved on the server (S8.3): title and number from our policy table. */
export interface DecisionSource {
  doc_key: string | null;
  version: number | null;
  document_title: string | null;
  section_id: string | null;
  href: string; // /policies#<doc>-<section>, the document, or the page when the section changed
  section_changed: boolean;
  policy_revised?: boolean;
  note: string | null;
}

export interface PolicySectionDetail extends PolicySection {
  document_id: string;
  document_title: string;
  version: number;
  in_force_from: string;
  in_force_to: string | null;
}

export interface Citation {
  section_ref: string;
  doc_key: string;
  version: number | string;
}

/** A case that needs a person (GET /cases/queue, S7.3). */
export interface QueueItem {
  case_id: string;
  order_ref: string | null;
  location_name: string | null;
  category: string | null;
  status: string;
  reason_kind: "escalated" | "awaiting_approval";
  reason_code: string;
  reason: string;
  waiting_since: string;
  waiting_seconds: number;
  owner_user_id: string | null;
  owner_name: string | null;
  owned_by_me: boolean;
  language: string;
  amount_paise: number | null;
  proposal_id: string | null;
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
  basis?: string[]; // which rule set the amount (S8.3)
  sources?: DecisionSource[]; // cited sections as links (S8.3)
  offer?: StaffOffer | null; // S8.10: the question put to the customer, if any
  queue_reason?: "customer_chose" | "no_customer_answer" | "safety_review" | null; // S8.10
}

/** S8.10: what an approver sees of a question put to the customer. */
export interface StaffOffer {
  state: "open" | "expired";
  asked_at: string;
  expires_at: string;
  options: { code: string; kind: string; amount_paise: number }[];
}

export interface OfferedOption {
  code: string;
  action: string;
  amount_paise: number;
}

export interface AskSuggestion {
  proposal_id: string;
  can_ask: boolean;
  blocked_reason: string | null;
  answer_days: number;
  options: OfferedOption[];
}

export interface AskResult {
  proposal_id: string;
  expires_at: string;
  options: OfferedOption[];
}

/** S8.10: what the customer sees. Text comes from server templates in the case language. */
export interface CustomerOffer {
  state: "none" | "open" | "chosen" | "expired" | "review";
  heading: string;
  intro: string;
  expires_note: string;
  status_text: string;
  options: RemedyOption[];
  expires_at?: string | null;
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

export interface SwitchAlternative {
  action: string;
  min_paise: number;
  max_paise: number;
  step_paise: number;
  needs_hq_above_paise: number | null;
  you_can_approve_up_to_paise: number;
}

export interface Alternatives {
  proposal_id: string;
  current_action: string;
  current_amount_paise: number | null;
  alternatives: SwitchAlternative[];
}

export interface SwitchResponse {
  old_proposal_id: string;
  proposal_id: string;
  action: string;
  amount_paise: number | null;
  decision: "approved" | null;
  waiting_for: "hq_owner" | "second_person" | string | null;
  self_approved?: "downgrade" | "owner_override" | null;
  expires_at: string | null;
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

export interface ConsentPurposeCopy {
  purpose: string;
  channel: string;
  granted: boolean;
  title: string;
  benefit: string;
  sent: string;
  cap: string;
  cap_days: number;
  channel_label: string;
  switch_label: string;
  state_label: string;
}

export interface ConsentHistoryCopy extends ConsentEvent {
  purpose_label: string;
  channel_label: string;
  action_label: string;
}

export interface ConsentBenefits {
  language: string;
  headings: Record<"title" | "intro" | "history" | "note" | "on" | "off" | "notice", string>;
  always_on: { title: string; body: string; badge: string };
  purposes: ConsentPurposeCopy[];
  history_labelled: ConsentHistoryCopy[];
}

export interface Consents {
  notice_version: string;
  consents: ConsentState[];
  history: ConsentEvent[];
  benefits: ConsentBenefits;
}

export interface HeldItem {
  key: string;
  label: string;
  purpose: string;
  use: "help" | "marketing";
  use_label: string;
  retention: string;
  retention_provisional: boolean;
  value: string | null;
  count: number | null;
  summary: string;
}

export interface PrivacyContact {
  label: string;
  configured: boolean;
  name: string;
  email: string;
  response_target_days: number;
  response_text: string;
}

export interface DataHeld {
  language: string;
  headings: Record<"title" | "item" | "yours" | "purpose" | "keep" | "use" | "processors" | "not_kept" | "contact", string>;
  items: HeldItem[];
  processors: { name: string; role: string; data: string }[];
  not_kept: string[];
  provisional_label: string | null;
  contact: PrivacyContact;
}

export type ErasureStage = "received" | "deferred" | "done" | "withdrawn";
export interface ExportField {
  label: string;
  value: string;
}

export interface ExportSection {
  key: string;
  title: string;
  purpose: string | null;
  retention: string | null;
  retention_provisional: boolean;
  records: ExportField[][];
  history?: ExportField[][];
}

export interface ReadableExport {
  language: string;
  title: string;
  generated: string;
  tz_note: string;
  labels: { why: string; howlong: string; empty: string; history: string; print: string; back: string };
  provisional_label: string | null;
  sections: ExportSection[];
  contact: PrivacyContact;
}

export interface ErasureRequest {
  id: string;
  kind: string;
  status: "pending_approval" | "deferred" | "completed" | "withdrawn";
  stage: ErasureStage;
  stage_label: string;
  stage_text: string;
  reason_code: string | null;
  reason: string | null;
  deferred_until: string | null;
  received_at: string;
  received_text: string;
  expected_by: string | null;
  expected_text: string | null;
  completed_at: string | null;
  // What happened to the one completion message; null until it is final.
  completion_message: "sent" | "failed" | "unknown" | "expired" | "none" | null;
  can_withdraw: boolean;
  contact: PrivacyContact;
}

export interface ErasureInfo {
  language: string;
  title: string;
  intro: string;
  headings: Record<"remove" | "keep" | "wait", string>;
  remove: string[];
  keep: { key: string; label: string; reason: string; provisional: boolean }[];
  wait: string[];
  provisional_label: string | null;
  timing: string;
  target_days: number;
  contact: PrivacyContact;
  completion_notice: {
    channels: ("phone" | "email")[];
    default: "phone" | "email" | null;
    labels: Record<string, string>;
    text: string;
    choose: string;
  };
  buttons: Record<"request" | "confirm" | "back" | "withdraw", string>;
  confirm: { title: string; body: string };
  status_title: string;
}

export interface RemedyOption {
  code: string;
  kind: "voucher" | "refund" | string;
  title: string;
  summary: string; // amount computed by the server
  amount_paise: number;
  approval: "instant" | "team" | string;
  timing: string;
}

export interface RemedyOptions {
  options: RemedyOption[];
  choice_required: boolean;
}

export interface StaffRemedyOption {
  action: string;
  min_paise: number;
  max_paise: number;
}

export interface StaffRemedyOptions {
  categories: string[];
  category: string | null;
  options: StaffRemedyOption[];
  note: string | null;
}

export interface ProposedRemedy {
  proposal_id: string;
  case_id: string;
  action: string;
  amount_paise: number | null;
  created: boolean;
  status: "awaiting_approval" | "approved" | "executed" | "rejected" | "expired";
  needs_hq: boolean;
}
