import DOMPurify from "dompurify";
import { marked } from "marked";
import customer from "../../../docs/manual/customer.md?raw";
import franchiseeOwner from "../../../docs/manual/franchisee_owner.md?raw";
import hqOwner from "../../../docs/manual/hq_owner.md?raw";
import locationManager from "../../../docs/manual/location_manager.md?raw";

// The manuals are bundled at build time from docs/manual, so the repo docs and the in-app Help
// are the same file and can't drift apart.
const MANUALS: Record<string, string> = {
  customer,
  location_manager: locationManager,
  franchisee_owner: franchiseeOwner,
  hq_owner: hqOwner,
};

export function manualMarkdown(role: string): string | null {
  return MANUALS[role] ?? null;
}

/** Markdown → sanitised HTML. The source is ours, but sanitising keeps it safe if that changes. */
export function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false, gfm: true }) as string;
  return DOMPurify.sanitize(html);
}
