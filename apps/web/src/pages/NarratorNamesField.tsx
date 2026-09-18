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
    if (!value || values.length >= 32) return;
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
      <ul className="preference-order">
        {values.map((value, index) => (
          <li key={`${index}:${value}`}>
            <span>{value}</span>
            <div>
              {ordered && (
                <>
                  <button
                    type="button"
                    disabled={index === 0}
                    aria-label={`Move ${value} up in ${label}`}
                    onClick={() => {
                      const next = [...values];
                      [next[index - 1], next[index]] = [
                        next[index],
                        next[index - 1],
                      ];
                      onChange(next);
                    }}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={index === values.length - 1}
                    aria-label={`Move ${value} down in ${label}`}
                    onClick={() => {
                      const next = [...values];
                      [next[index + 1], next[index]] = [
                        next[index],
                        next[index + 1],
                      ];
                      onChange(next);
                    }}
                  >
                    ↓
                  </button>
                </>
              )}
              <button
                type="button"
                aria-label={`Remove ${value} from ${label}`}
                onClick={() => onChange(values.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
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
