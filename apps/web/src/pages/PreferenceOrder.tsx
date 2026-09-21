import type { ReactNode } from "react";
import { X } from "lucide-react";
import Sortable from "../components/Sortable";
export default function PreferenceOrder({
  label,
  values,
  onChange,
  valid = () => true,
  names = {},
  onRemove,
  help,
}: {
  label: string;
  help?: ReactNode;
  values: string[];
  onChange: (values: string[]) => void;
  valid?: (values: string[]) => boolean;
  names?: Record<string, string>;
  onRemove?: (value: string) => void;
}) {
  const display = (value: string) =>
    names[value] ||
    {
      format: "Format",
      source: "Source",
      seeders: "Seeders",
      popularity: "Popularity",
      narrator: "Narrator",
    }[value] ||
    value.toUpperCase();
  return (
    <fieldset>
      <legend>
        <span className="setting-subheading">
          {label}
          {help}
        </span>
      </legend>
      <Sortable
        label={label}
        values={values}
        onChange={onChange}
        valid={valid}
        render={(value) => (
          <>
            <span>{display(value)}</span>
            {onRemove && (
              <button
                type="button"
                className="sort-remove"
                aria-label={`Remove ${names[value] || value} from ${label}`}
                disabled={values.length <= 1}
                onClick={() => onRemove(value)}
              >
                <X size={14} />
              </button>
            )}
          </>
        )}
      />
    </fieldset>
  );
}
