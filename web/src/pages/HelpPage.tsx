import { useMemo, useState } from "react";
import type { Language } from "../api/types";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { useApi } from "../lib/useApi";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { manualMarkdown, renderMarkdown } from "../manual";
import { roleLabel } from "../lib/roles";

const LANGUAGE_OPTIONS: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi-Latn", label: "Hinglish (Hindi in English letters)" },
  { value: "hi", label: "हिन्दी (Devanagari)" },
];

/** Customers only. This app's own labels stay English; only our messages about a case change. */
function LanguageCard() {
  const { data, error } = useApi(() => api.preferences(), []);
  const [saved, setSaved] = useState<Language | null>(null);
  const [failed, setFailed] = useState(false);
  const value = saved ?? data?.language ?? "en";
  async function choose(language: Language) {
    setFailed(false);
    try {
      const res = await api.setPreferences(language);
      setSaved(res.language);
    } catch {
      setFailed(true);
    }
  }
  return (
    <Card className="mb-4 p-4">
      <h2 className="text-sm font-semibold text-slate-900">Language for our messages</h2>
      <p className="mt-1 text-sm text-slate-600">
        Choose the language we use when we write to you about a report. The rest of this app stays
        in English.
      </p>
      <select
        aria-label="Language for our messages"
        className="mt-2 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
        value={value}
        disabled={!data && !error}
        onChange={(e) => choose(e.target.value as Language)}
      >
        {LANGUAGE_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {failed && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          Could not save your choice. Try again.
        </p>
      )}
    </Card>
  );
}

export function HelpPage() {
  const { me } = useAuth();
  const role = me?.role ?? "";
  const { data: privacy } = useApi(() => api.privacyContact(), [role]);
  const html = useMemo(() => {
    const md = manualMarkdown(role);
    return md ? renderMarkdown(md) : null;
  }, [role]);

  return (
    <>
      <PageHeader title="Help" subtitle={`The manual for your role: ${roleLabel(role)}.`} />
      {role === "customer" && <LanguageCard />}
      {privacy && privacy.email && (
        <Card className="mb-4 p-4">
          <h2 className="text-sm font-semibold text-slate-900">Privacy contact</h2>
          <p className="mt-1 text-sm text-slate-600">
            For questions about your personal data, or to make a privacy request: {privacy.name},{" "}
            <a className="underline" href={`mailto:${privacy.email}`}>
              {privacy.email}
            </a>
            . You can also report a problem on an order and choose the privacy request category.
          </p>
        </Card>
      )}
      {html ? (
        <Card className="p-5 sm:p-8">
          {/* Sanitised with DOMPurify in renderMarkdown. */}
          <article className="manual" dangerouslySetInnerHTML={{ __html: html }} />
        </Card>
      ) : (
        <EmptyState title="No manual for this role yet" />
      )}
    </>
  );
}
