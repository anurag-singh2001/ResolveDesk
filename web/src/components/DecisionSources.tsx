import { Link } from "react-router-dom";
import type { DecisionSource } from "../api/types";

/** Which rule set the amount: plain lines the server built from fixed templates (S8.3). */
export function RemedyBasis({ lines }: { lines?: string[] }) {
  if (!lines || lines.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1 text-xs text-muted-foreground" aria-label="Why this amount" data-testid="remedy-basis">
      {lines.map((line, i) => (
        <li key={i}>{line}</li>
      ))}
    </ul>
  );
}

/** The policy sections a decision relied on, as links to the exact section. Only the document
 *  title and section number from our own policy table are shown, never the text a model quoted
 *  (policy text is untrusted, hard rule 9). A section that changed falls back to the document
 *  and says so. */
export function SourceLinks({ sources, showVersion = false }: { sources?: DecisionSource[]; showVersion?: boolean }) {
  if (!sources || sources.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1.5 text-sm" aria-label="Policy sources" data-testid="policy-sources">
      {sources.map((s, i) => (
        <li key={`${s.doc_key}-${s.section_id}-${i}`}>
          <Link
            to={s.href}
            className="text-foreground underline underline-offset-2 transition-colors duration-200 hover:text-brand"
          >
            {s.document_title ?? "Our policies"}
            {s.section_id ? `, section ${s.section_id}` : ""}
          </Link>
          {showVersion && s.version != null && <span className="ml-2 font-mono text-xs text-muted-foreground">v{s.version}</span>}
          {s.note && <p className="mt-0.5 text-xs text-muted-foreground">{s.note}</p>}
        </li>
      ))}
    </ul>
  );
}
