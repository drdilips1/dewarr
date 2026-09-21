import Sortable from "../components/Sortable";
import { useState } from "react";

export default function NarratorNamesField({
  label,
  values,
  onChange,
  ordered = false,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  ordered?: boolean;
}) {
  const [name, setName] = useState("");
  const add = () => {
    const value = name.normalize("NFKC").trim().replace(/\s+/g, " ");
    if (!value || values.includes(value) || values.length >= 32) return;
    onChange([...values, value]);
    setName("");
  };
  return (
    <fieldset>
      <legend>{label}</legend>
      <p className="muted">
        {ordered
          ? "Earlier names are preferred. Other narrators remain eligible."
          : "Every listed narrator is required for audio requests. Leave empty to accept any narrator."}
      </p>
      <Sortable
        label={label}
        values={values}
        onChange={onChange}
        render={(value) => (
          <>
            <span>{value}</span>
            <button
              type="button"
              className="sort-remove"
              aria-label={`Remove ${value} from ${label}`}
              onClick={() => onChange(values.filter((item) => item !== value))}
            >
              Remove
            </button>
          </>
        )}
      />
      <label>
        {label} name
        <input
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
      </label>
      <button
        type="button"
        disabled={!name.trim() || values.length >= 32}
        onClick={add}
      >
        Add to {label.toLowerCase()}
      </button>
    </fieldset>
  );
}
