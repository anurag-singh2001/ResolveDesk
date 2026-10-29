import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { RemedyOption } from "../api/types";
import { Alert, Button, Card } from "./ui";

/** Radio list of the remedies the rule allows. All text (amount, timing) comes from the server. */
export function RemedyChoice({
  options,
  value,
  onChange,
}: {
  options: RemedyOption[];
  value: string;
  onChange: (code: string) => void;
}) {
  if (options.length < 2) return null; // a single option is not a choice
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-slate-900">How would you like this settled?</legend>
      {options.map((o) => (
        <label
          key={o.code}
          className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-3 has-[:checked]:border-slate-900"
        >
          <input
            type="radio"
            name="remedy_choice"
            value={o.code}
            checked={value === o.code}
            onChange={() => onChange(o.code)}
            className="mt-1"
          />
          <span className="text-sm">
            <span className="block font-medium text-slate-900">{o.title}</span>
            <span className="block text-slate-700">{o.summary}</span>
            <span className="block text-xs text-slate-500">{o.timing}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Case page, customer only: shown while the case is undecided and the rule offers a choice. */
export function CaseRemedyChoice({ caseId }: { caseId: string }) {
  const [options, setOptions] = useState<RemedyOption[]>([]);
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .caseRemedyOptions(caseId)
      .then((r) => {
        if (!live || !r.choice_required) return;
        setOptions(r.options);
        setValue(r.options[0]?.code ?? "");
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [caseId]);

  if (options.length < 2) return null;

  async function save() {
    setError(null);
    try {
      await api.setRemedyChoice(caseId, value);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card className="p-4">
      <RemedyChoice
        options={options}
        value={value}
        onChange={(c) => {
          setValue(c);
          setSaved(false);
        }}
      />
      {error && <Alert>{error}</Alert>}
      <div className="mt-3 flex items-center gap-3">
        <Button type="button" onClick={save}>
          Save my choice
        </Button>
        {saved && <span className="text-sm text-slate-600">Saved.</span>}
      </div>
    </Card>
  );
}
