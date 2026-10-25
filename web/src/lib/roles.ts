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
  icon: "orders" | "cases" | "approvals" | "help";
}

/** Which screens a role sees. The API still enforces access on every call. */
export function navFor(role: string): NavItem[] {
  if (role === "customer") {
    return [
      { to: "/orders", label: "My orders", icon: "orders" },
      { to: "/cases", label: "My cases", icon: "cases" },
      { to: "/help", label: "Help", icon: "help" },
    ];
  }
  if (isStaff(role)) {
    return [
      { to: "/approvals", label: "Approvals", icon: "approvals" },
      { to: "/cases", label: "Cases", icon: "cases" },
      { to: "/help", label: "Help", icon: "help" },
    ];
  }
  return [{ to: "/help", label: "Help", icon: "help" }];
}

export function homePath(role: string): string {
  return role === "customer" ? "/orders" : isStaff(role) ? "/approvals" : "/help";
}
