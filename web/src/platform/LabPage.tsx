import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { Alert, Badge, Button, EmptyState, ErrorState, Field, Loading, PageHeader, inputClass, tableClass, tableWrapClass, tdClass, thClass } from "../components/ui";
import { useApi } from "../lib/useApi";
import { Section } from "./parts";
import { usePlatform } from "./session";
import type { LabComparison, LabListing, LabRun } from "./types";

const NEW_TEXT = `id: new-scenario-001
tenant: TENANT
kind: plain
message: Write the customer's message here.
order:
  select: latest
expect:
  category: null
  outcome: escalated
held_out: false
`;

/** The server's readable problems for a 422, else a generic line. Scenario text is shown as text only. */
function problemsOf(err: unknown): string[] {
  if (err instanceof ApiError) {
    const d = err.detail as { problems?: unknown } | string | null;
    if (d && typeof d === "object" && Array.isArray(d.problems)) return d.problems.map(String);
    if (typeof d === "string") return [d];
  }
  return ["That did not work. Please try again."];
}

const CHANGE_TONE: Record<string, "success" | "danger" | "neutral"> = { improved: "success", regressed: "danger", same: "neutral", unknown: "neutral" };

function Comparison({ c }: { c: LabComparison }) {
  return (
    <>
      <p className="mb-3 text-sm text-muted-foreground">
        {c.last_report ? `Compared with the last full report: ${c.last_report.name}.` : "There is no earlier full report to compare with."}
      </p>
      <div className={tableWrapClass}>
        <table className={tableClass}>
          <thead>
            <tr>
              {["Scenario", "Pipeline", "Last report", "This run", "Change"].map((h) => (
                <th key={h} className={thClass}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.scenarios.map((r) => (
              <tr key={`${r.id}/${r.pipeline}`}>
                <td className={tdClass}>{r.id}</td>
                <td className={tdClass}>{r.pipeline}</td>
                <td className={tdClass}>{r.before}</td>
                <td className={tdClass}>{r.now}</td>
                <td className={tdClass}><Badge tone={CHANGE_TONE[r.change] ?? "neutral"}>{r.change}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c.new_rows.map((n) => {
        const was = c.last_rows.find((l) => l.tenant === n.tenant && l.pipeline === n.pipeline);
        return (
          <p key={`${n.tenant}/${n.pipeline}`} className="mt-3 text-sm text-foreground">
            {n.pipeline}: pass {n.metrics["pass"] ?? "-"} on {n.metrics["cases"] ?? "-"} scenarios
            {was ? `; last report ${was.metrics["pass"] ?? "-"} on ${was.metrics["cases"] ?? "-"}` : ""}
          </p>
        );
      })}
    </>
  );
}

export function LabPage() {
  const { get, send } = usePlatform();
  const [tenant, setTenant] = useState<string>("");
  const { data: fresh, error, loading, reload } = useApi(
    () => get<LabListing>(`/lab/scenarios?tenant=${encodeURIComponent(tenant)}`),
    [get, tenant],
  );
  // Keep showing the last listing while a new one loads (switching business, saving).
  const [data, setData] = useState<LabListing | undefined>(undefined);
  useEffect(() => {
    if (fresh) setData(fresh);
  }, [fresh]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [pipeline, setPipeline] = useState("agents");
  const [editId, setEditId] = useState<string | null>(null); // null: nothing open; "" : a new one
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [readOnly, setReadOnly] = useState(false); // a held-out scenario is shown but never saved
  const [problems, setProblems] = useState<string[]>([]);
  const [info, setInfo] = useState<string | null>(null);
  const [run, setRun] = useState<LabRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const tenants = data?.tenants ?? [];
  useEffect(() => {
    if (!tenant && tenants.length > 0) setTenant(tenants[0]);
  }, [tenant, tenants]);

  const poll = useCallback(async () => {
    try {
      setRun(await get<LabRun>("/lab/runs/current"));
    } catch {
      /* the next tick tries again */
    }
  }, [get]);
  useEffect(() => {
    void poll();
  }, [poll]);
  useEffect(() => {
    if (run?.status !== "running") return;
    const id = window.setInterval(() => void poll(), 3000);
    return () => window.clearInterval(id);
  }, [run?.status, poll]);

  const open = async (id: string) => {
    setProblems([]);
    setInfo(null);
    try {
      const out = await get<{ yaml: string }>(`/lab/scenarios/${tenant}/${id}`);
      setEditId(id);
      setName(id);
      setText(out.yaml);
      setReadOnly(Boolean(data?.scenarios.find((s) => s.id === id)?.held_out));
    } catch (err) {
      setProblems(problemsOf(err));
    }
  };
  const startNew = () => {
    setReadOnly(false);
    setEditId("");
    setName("");
    setText(NEW_TEXT.replace("TENANT", tenant));
    setProblems([]);
    setInfo(null);
  };
  const validate = async () => {
    try {
      const out = await send<{ ok: boolean; problems: string[] }>("POST", `/lab/validate/${tenant}`, { yaml: text });
      setProblems(out.problems);
      setInfo(out.ok ? "This scenario is valid." : null);
    } catch (err) {
      setProblems(problemsOf(err));
    }
  };
  const save = async () => {
    setInfo(null);
    try {
      await send("PUT", `/lab/scenarios/${tenant}/${name}`, { yaml: text });
      setProblems([]);
      setInfo(`Saved ${name}.`);
      setEditId(name);
      void reload();
    } catch (err) {
      setProblems(problemsOf(err));
    }
  };
  const start = async () => {
    setRunError(null);
    try {
      setRun(await send<LabRun>("POST", "/lab/runs", { tenant, ids: [...picked], pipeline }));
    } catch (err) {
      setRunError(problemsOf(err).join(" "));
    }
  };
  const toggle = (id: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const running = run?.status === "running";
  const scratch = data?.scratch_configured ?? false;

  return (
    <>
      <PageHeader title="Scenario lab" subtitle="Edit scenario files and run a few of them against a scratch database, never the demo data. Runs use the real models, one at a time." />
      {loading && !data && <Loading />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void reload()} /> : null}
      {data && (
        <>
          <div className="mb-4 max-w-xs">
            <Field label="Business" htmlFor="lab-tenant">
              <select id="lab-tenant" className={inputClass} value={tenant} onChange={(e) => { setTenant(e.target.value); setPicked(new Set()); setEditId(null); }}>
                {tenants.map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
            </Field>
          </div>
          <Section title="Scenarios">
            {data.scenarios.length === 0 ? (
              <EmptyState title="No scenarios">This business has no scenario files yet.</EmptyState>
            ) : (
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <th className={thClass}>Run</th>
                      <th className={thClass}>Scenario</th>
                      <th className={thClass}>Kind</th>
                      <th className={thClass}>Message</th>
                      <th className={thClass}>Edit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.scenarios.map((s) => (
                      <tr key={s.id}>
                        <td className={tdClass}><input type="checkbox" aria-label={`Run ${s.id}`} checked={picked.has(s.id)} onChange={() => toggle(s.id)} /></td>
                        <td className={tdClass}>{s.id}{s.held_out ? " (held out)" : ""}</td>
                        <td className={tdClass}>{s.kind}</td>
                        <td className={tdClass}>{s.message}</td>
                        <td className={tdClass}><Button variant="outline" onClick={() => void open(s.id)} aria-label={`Edit ${s.id}`}>Edit</Button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-3"><Button variant="outline" onClick={startNew}>New scenario</Button></div>
          </Section>

          {editId !== null && (
            <Section title={editId === "" ? "New scenario" : `Edit ${editId}`} note="The file is checked against the same rules the evals use. The id must match the name.">
              <div className="mb-3 max-w-xs">
                <Field label="Name (id)" htmlFor="lab-name" hint="Lowercase letters, digits and dashes.">
                  <input id="lab-name" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} disabled={editId !== ""} />
                </Field>
              </div>
              <Field label="Scenario YAML" htmlFor="lab-yaml">
                <textarea id="lab-yaml" className={`${inputClass} h-72 font-mono`} readOnly={readOnly} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
              </Field>
              {problems.length > 0 && (
                <div className="mt-3">
                  <Alert>
                    <ul className="list-disc pl-5">{problems.map((p) => (<li key={p}>{p}</li>))}</ul>
                  </Alert>
                </div>
              )}
              {readOnly && <div className="mt-3"><Alert tone="info">This scenario is held out, so it is read-only here. You can read it and check it, but not save it.</Alert></div>}
              {info && <div className="mt-3"><Alert tone="success">{info}</Alert></div>}
              <div className="mt-3 flex gap-2">
                <Button variant="outline" onClick={() => void validate()}>Check</Button>
                {!readOnly && <Button onClick={() => void save()} disabled={!name}>Save</Button>}
              </div>
            </Section>
          )}
          {editId === null && problems.length > 0 && <Alert>{problems.join(" ")}</Alert>}

          <Section title="Run" note="Runs the chosen scenarios on the lab's scratch database. It can take several minutes; this page keeps checking.">
            {!scratch && (
              <Alert tone="warning">No scratch database is set up for the lab, so nothing can be run. You can still edit scenarios.</Alert>
            )}
            <div className="my-3 flex flex-wrap items-end gap-3">
              <div className="w-48">
                <Field label="Pipeline" htmlFor="lab-pipeline">
                  <select id="lab-pipeline" className={inputClass} value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
                    <option value="agents">agents</option>
                    <option value="baseline">baseline</option>
                    <option value="both">both</option>
                  </select>
                </Field>
              </div>
              <Button onClick={() => void start()} disabled={!scratch || running || picked.size === 0}>
                {running ? "Running…" : `Run ${picked.size} scenario${picked.size === 1 ? "" : "s"}`}
              </Button>
            </div>
            {runError && <Alert>{runError}</Alert>}
            {run && run.status !== "idle" && (
              <p className="my-3 text-sm text-foreground" role="status">
                Run {run.run_id}: {run.status}
                {run.message ? `. ${run.message}` : ""} ({run.ids.length} scenario{run.ids.length === 1 ? "" : "s"}, {run.pipeline})
              </p>
            )}
            {run?.comparison && <Comparison c={run.comparison} />}
          </Section>
        </>
      )}
    </>
  );
}
