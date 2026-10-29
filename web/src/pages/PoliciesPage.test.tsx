import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PolicyDoc, Role, RulesSummary } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const HOSTILE = '<script>window.__pwned = 1</script><img src=x onerror="window.__pwned = 1"> **bold** [x](javascript:alert(1))';

const docs: PolicyDoc[] = [
  {
    id: "late_delivery_v3",
    title: "Late delivery policy",
    topic: "late_delivery",
    version: 3,
    in_force_from: "2026-09-01",
    in_force_to: null,
    scope: "org",
    sections: [
      { id: "2.1", anchor: "late_delivery_v3-2.1", title: "More than 45 minutes late", text: "We offer a voucher.\n\n- Up to Rs 150\n- Once per order" },
      { id: "2.2", anchor: "late_delivery_v3-2.2", title: HOSTILE, text: HOSTILE },
    ],
  },
];

const line = { approval_text: null, max_paise: null, percent: null, min_minutes_late: null, label: null };
const rules: RulesSummary = {
  language: "en",
  pack_name: "Cloud kitchen",
  pack_version: 1,
  pack_updated: "2026-10-01",
  settings_updated: "2026-10-20",
  in_force_since: "2026-10-20",
  in_force_text: "These rules have been in force since 20 Oct 2026.",
  categories: [
    {
      category: "wrong_item",
      title: "You got the wrong item",
      decided_by: "mixed",
      setting_keys: ["voucher_max_paise"],
      notes: ["If you already had 3 refunds or vouchers in the last 30 days, a team member decides instead."],
      tiers: [],
      options: [
        { ...line, code: "voucher", kind: "voucher", text: "A voucher up to the value of your order, at most ₹150.00.", approval: "instant", approval_text: "Usually instant.", max_paise: 15000, percent: 100 },
        { ...line, code: "refund_50pct", kind: "refund", text: "A refund of up to 50% of your order, never more than you paid.", approval: "team", approval_text: "After a team member approves it.", percent: 50 },
      ],
    },
    {
      category: "late_delivery",
      title: "Your order is late",
      decided_by: "mixed",
      setting_keys: [],
      notes: [],
      options: [],
      tiers: [
        { ...line, code: "apology", kind: "apology", text: "We apologise and note it with the team.", approval: null, min_minutes_late: 0, label: "0 minutes late or more" },
        { ...line, code: "refund", kind: "refund", text: "A refund of up to 50% of your order, never more than you paid.", approval: "team", approval_text: "After a team member approves it.", percent: 50, min_minutes_late: 45, label: "45 minutes late or more" },
      ],
    },
  ],
  settings: [],
};

function setup(role: Role, summary: RulesSummary = rules) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /policies": { body: docs },
    "GET /policies/rules-summary": { body: summary },
    "GET /orders": { body: [] },
    "GET /approvals": { body: [] },
    "GET /cases/queue": { body: [] },
    "GET /meta/privacy": { body: { name: "", email: "" } },
  });
}

describe("policies page", () => {
  it("shows documents and sections with an anchor per section, without the version, to a customer", async () => {
    setup("customer");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Our policies" });
    const section = document.getElementById("late_delivery_v3-2.1");
    expect(section).not.toBeNull();
    expect(within(section as HTMLElement).getByText("Up to Rs 150").tagName).toBe("LI");
    expect(screen.getByTestId("meta-late_delivery_v3")).toHaveTextContent("In force from 2026-09-01");
    expect(screen.getByTestId("meta-late_delivery_v3")).not.toHaveTextContent("Version");
    const link = screen.getAllByRole("link", { name: /2\.1 More than 45 minutes late/ })[0];
    expect(link).toHaveAttribute("href", "#late_delivery_v3-2.1");
  });

  it("shows the version and date in force to staff", async () => {
    setup("hq_owner");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Policies" });
    expect(screen.getByTestId("meta-late_delivery_v3")).toHaveTextContent("Version 3, in force from 2026-09-01");
  });

  it("renders markup in policy text as inert plain text", async () => {
    setup("customer");
    renderApp("/policies");
    await screen.findByRole("heading", { name: "Our policies" });
    const main = screen.getByRole("main");
    expect(main.querySelector("script")).toBeNull();
    expect(main.querySelector("img")).toBeNull();
    expect(main.querySelector("a[href^='javascript']")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    // The literal characters are visible.
    expect(screen.getAllByText(/<script>window\.__pwned = 1<\/script>/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\*\*bold\*\*/).length).toBeGreaterThan(0);
  });

  it("shows an empty state when nothing is published", async () => {
    seedSession();
    mockFetch({ "GET /me": { body: makeMe("customer") }, "GET /policies": { body: [] }, "GET /orders": { body: [] } });
    renderApp("/policies");
    expect(await screen.findByText("No policies are published yet")).toBeInTheDocument();
  });

  it("shows the rules in plain words to a customer, without setting keys", async () => {
    setup("customer");
    renderApp("/policies");
    const block = await screen.findByTestId("rule-wrong_item");
    expect(screen.getByRole("heading", { name: "Rules in plain words" })).toBeInTheDocument();
    expect(within(block).getByText(/at most ₹150\.00/)).toBeInTheDocument();
    expect(within(block).getByText("After a team member approves it.")).toBeInTheDocument();
    expect(within(screen.getByTestId("rule-late_delivery")).getByText("45 minutes late or more")).toBeInTheDocument();
    expect(screen.getByTestId("rules-in-force")).toHaveTextContent("in force since 20 Oct 2026");
    expect(screen.getByTestId("rules-in-force")).not.toHaveTextContent("version");
    expect(screen.queryByText("Settings behind these rules")).toBeNull();
  });

  it("shows staff the pack version and which level set each setting", async () => {
    setup("hq_owner", {
      ...rules,
      settings: [
        { key: "voucher_max_paise", value: 30000, source: "pack_default" },
        { key: "late_delivery_tiers", value: [{ min_minutes_late: 0, remedy: "apology" }], source: "tenant_override" },
      ],
    });
    renderApp("/policies");
    await screen.findByText("Settings behind these rules");
    expect(screen.getByTestId("rules-in-force")).toHaveTextContent("version 1");
    expect(within(screen.getByTestId("setting-voucher_max_paise")).getByText("Pack default")).toBeInTheDocument();
    expect(within(screen.getByTestId("setting-late_delivery_tiers")).getByText("Tenant override")).toBeInTheDocument();
  });
});
