import type { Role } from "../api/types";

export const ROLE_LABEL: Record<Role, string> = {
  customer: "Customer",
  location_manager: "Location manager",
  franchisee_owner: "Franchisee owner",
  hq_owner: "HQ owner",
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role as Role] ?? role;
}

export function isStaff(role: string | undefined): boolean {
  return role === "location_manager" || role === "franchisee_owner" || role === "hq_owner";
}

export interface NavItem {
  to: string;
  label: string;
  icon: "orders" | "cases" | "approvals" | "help" | "dev" | "insights" | "dashboard" | "growth" | "privacy" | "policies";
}

/** Which screens a role sees. The API still enforces access on every call. */
export function canSeeInsights(role: string | undefined): boolean {
  return role === "hq_owner" || role === "franchisee_owner";
}

/** Growth is staff-only and only where the tenant's growth flag is on (GET /me). */
export function canSeeGrowth(role: string | undefined, growthEnabled: boolean | undefined): boolean {
  return isStaff(role) && growthEnabled === true;
}

export function navFor(role: string, growthEnabled = false): NavItem[] {
  if (role === "customer") {
    return [
      { to: "/orders", label: "My orders", icon: "orders" },
      { to: "/cases", label: "My cases", icon: "cases" },
      { to: "/policies", label: "Our policies", icon: "policies" },
      { to: "/privacy", label: "Privacy & data", icon: "privacy" },
      { to: "/help", label: "Help", icon: "help" },
    ];
  }
  if (isStaff(role)) {
    return [
      { to: "/approvals", label: "Approvals", icon: "approvals" },
      { to: "/queue", label: "Cases to handle", icon: "cases" },
      { to: "/cases", label: "Cases", icon: "cases" },
      { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
      ...(canSeeInsights(role) ? [{ to: "/insights", label: "Insights", icon: "insights" as const }] : []),
      ...(canSeeGrowth(role, growthEnabled) ? [{ to: "/growth", label: "Growth", icon: "growth" as const }] : []),
      ...(role === "hq_owner" ? [{ to: "/privacy-requests", label: "Privacy requests", icon: "privacy" as const }] : []),
      { to: "/policies", label: "Policies", icon: "policies" },
      { to: "/help", label: "Help", icon: "help" },
    ];
  }
  return [{ to: "/help", label: "Help", icon: "help" }];
}

export function homePath(role: string): string {
  return role === "customer" ? "/orders" : isStaff(role) ? "/approvals" : "/help";
}
