import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Case, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const kase: Case = {
  id: "c-1",
  transaction_id: null,
  order_ref: "O1",
  category: "missing_items",
  stage: "escalated",
  message: "A member of our team will look into this.",
  action: null,
  amount_paise: null,
  proposal_id: null,
  created_at: "2026-10-25T10:00:00Z",
  staff_messages: [],
  closed: false,
  close_reason: null,
};

const templates = {
  language: "hi-Latn",
  templates: [
    { id: "looking_into", label: "We're looking into it", preview: "Hum ise dekh rahe hain aur aapko update denge." },
    { id: "share_photo", label: "Please share a photo", preview: "Kripya photo bhejiye." },
  ],
  close_reasons: [
    { id: "resolved", label: "Resolved" },
    { id: "duplicate", label: "Duplicate of another case" },
  ],
  note_max_length: 280,
  closed: false,
};

function setup(role: Role, c: Case = kase, extra: Record<string, { status?: number; body?: unknown }> = {}) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /cases/c-1": { body: c },
    "GET /cases/c-1/timeline": { body: [] },
    "GET /cases/c-1/reply-templates": { body: templates },
    "POST /cases/c-1/staff-reply": { body: { sent: true } },
    "POST /cases/c-1/close": { body: { case_id: "c-1", status: "closed", close_reason: "resolved" } },
    ...extra,
  });
}

describe("staff reply panel", () => {
  it("is not shown to customers and fetches no templates", async () => {
    const { calls } = setup("customer");
    renderApp("/cases/c-1");
    await screen.findByText(kase.message);
    expect(screen.queryByText("Reply to the customer")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("reply-templates"))).toBe(false);
  });

  it("previews the template in the case language, labels the note and sends once with a key", async () => {
    const { calls } = setup("location_manager");
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Message"), "looking_into");
    expect(screen.getByLabelText("Preview")).toHaveTextContent("Hum ise dekh rahe hain");
    await user.type(screen.getByLabelText(/Note from our team/), "Rider is nearby");
    await user.click(screen.getByRole("button", { name: "Send to customer" }));
    await screen.findByText("Sent to the customer.");
    const post = calls.find((c) => c.method === "POST" && c.path === "/cases/c-1/staff-reply");
    expect(post?.body).toMatchObject({ template_id: "looking_into", note: "Rider is nearby" });
    expect(typeof (post?.body as { idempotency_key: string }).idempotency_key).toBe("string");
    expect(calls.filter((c) => c.path === "/cases/c-1/staff-reply")).toHaveLength(1);
  });

  it("disables send until a template is chosen", async () => {
    setup("hq_owner");
    renderApp("/cases/c-1");
    expect(await screen.findByRole("button", { name: "Send to customer" })).toBeDisabled();
  });

  it("asks to confirm closing, focuses Cancel, and closes only on Yes", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Reason"), "resolved");
    await user.click(screen.getByRole("button", { name: "Close case…" }));
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    expect(calls.some((c) => c.path === "/cases/c-1/close")).toBe(false);
    await user.click(cancel);
    expect(calls.some((c) => c.path === "/cases/c-1/close")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Close case…" }));
    await user.click(screen.getByRole("button", { name: "Yes, close the case" }));
    const post = calls.find((c) => c.path === "/cases/c-1/close");
    expect(post?.body).toEqual({ reason: "resolved" });
  });

  it("shows the server's refusal when closing is blocked", async () => {
    setup("hq_owner", kase, {
      "POST /cases/c-1/close": { status: 409, body: { detail: "a remedy on this case is waiting for a decision" } },
    });
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Reason"), "duplicate");
    await user.click(screen.getByRole("button", { name: "Close case…" }));
    await user.click(screen.getByRole("button", { name: "Yes, close the case" }));
    expect(await screen.findByText(/waiting for a decision/)).toBeInTheDocument();
  });

  it("shows a closed case without reply controls, with what was sent", async () => {
    setup("location_manager", {
      ...kase,
      closed: true,
      close_reason: "resolved",
      staff_messages: [{ at: "2026-10-25T11:00:00Z", kind: "note", template_id: null, text: "Thanks for waiting", sender_user_id: "u-1" }],
    });
    renderApp("/cases/c-1");
    expect(await screen.findByText(/No further replies can be sent/)).toBeInTheDocument();
    expect(screen.getByText("Thanks for waiting")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to customer" })).not.toBeInTheDocument();
  });
});
