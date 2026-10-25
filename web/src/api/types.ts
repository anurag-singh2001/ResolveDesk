// Shapes from docs/api/frontend-contract.md. Fields marked NEW there are optional here so the
// app keeps working against a backend that doesn't send them yet.

export type Role = "customer" | "location_manager" | "franchisee_owner" | "hq_owner";

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
}

export interface Categories {
  categories: string[];
  free_text: boolean;
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
  customer_message?: string | null; // NEW
  location_name?: string | null; // NEW
  citations?: Citation[]; // NEW
}

export interface DecisionResponse {
  proposal_id: string;
  decision: "approved" | "rejected";
  expires_at: string;
  execution: string;
}
