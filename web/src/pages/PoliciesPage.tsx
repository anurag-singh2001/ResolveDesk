import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/session";
import { PlainPolicyText } from "../components/PlainPolicyText";
import { RulesSummarySection } from "../components/RulesSummary";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { humanize } from "../lib/format";
import { isStaff } from "../lib/roles";
import { useApi } from "../lib/useApi";

/** Anchor ids come from the API (`<doc>-<section>`), so /policies#<anchor> deep links work. */
export function PoliciesPage() {
  const { me } = useAuth();
  const staff = isStaff(me?.role);
  const { data, error, loading, reload } = useApi(() => api.policies(), [me?.role]);
  const hash = useLocation().hash.slice(1);

  useEffect(() => {
    if (!data || !hash) return;
    document.getElementById(decodeURIComponent(hash))?.scrollIntoView?.({ block: "start" });
  }, [data, hash]);

  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const docs = data ?? [];

  return (
    <>
      <PageHeader
        title={staff ? "Policies" : "Our policies"}
        subtitle={
          staff
            ? "The policy documents in force, with the version and the date each came into force."
            : "The rules we follow when we look into a problem with your order."
        }
      />
      <RulesSummarySection staff={staff} />
      {docs.length === 0 ? (
        <EmptyState title="No policies are published yet" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
          <nav aria-label="Policy contents" className="lg:sticky lg:top-24 lg:self-start">
            <ul className="space-y-3 text-sm">
              {docs.map((d) => (
                <li key={d.id}>
                  <a href={`#${d.id}`} className="font-medium text-foreground underline-offset-2 transition-colors duration-200 hover:text-brand hover:underline">
                    {d.title}
                  </a>
                  <ul className="mt-1 space-y-0.5 border-l border-border pl-3">
                    {d.sections.map((s) => (
                      <li key={s.anchor}>
                        <a href={`#${s.anchor}`} className="text-muted-foreground hover:text-foreground underline-offset-2 transition-colors duration-200 hover:text-brand hover:underline">
                          {s.id} {s.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </nav>
          <div className="space-y-6">
            {docs.map((d) => (
              <Card key={d.id} className="p-5 sm:p-6">
                <section id={d.id} aria-labelledby={`${d.id}-title`} className="scroll-mt-24">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 id={`${d.id}-title`} className="font-montserrat text-lg font-semibold text-foreground">
                      {d.title}
                    </h2>
                    {d.scope !== "org" && <Badge>{d.scope}</Badge>}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground" data-testid={`meta-${d.id}`}>
                    {staff
                      ? `Version ${d.version}, in force from ${d.in_force_from}${d.in_force_to ? ` until ${d.in_force_to}` : ""}. Topic: ${humanize(d.topic)}.`
                      : `In force from ${d.in_force_from}.`}
                  </p>
                  <div className="mt-4 space-y-5">
                    {d.sections.map((s) => (
                      <section key={s.anchor} id={s.anchor} aria-labelledby={`${s.anchor}-title`} className="scroll-mt-24">
                        <h3 id={`${s.anchor}-title`} className="font-montserrat text-sm font-semibold text-foreground">
                          <a href={`#${s.anchor}`} className="underline-offset-2 transition-colors duration-200 hover:text-brand hover:underline">
                            {s.id} {s.title}
                          </a>
                        </h3>
                        <div className="mt-1.5">
                          <PlainPolicyText text={s.text} />
                        </div>
                      </section>
                    ))}
                  </div>
                </section>
              </Card>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
