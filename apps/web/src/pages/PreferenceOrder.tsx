export default function PreferenceOrder({
  label,
  values,
  onChange,
  valid = () => true,
  names = {},
  onRemove,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  valid?: (values: string[]) => boolean;
  names?: Record<string, string>;
  onRemove?: (value: string) => void;
}) {
  const moved = (index: number, step: number) => {
    const next = [...values];
    [next[index], next[index + step]] = [next[index + step], next[index]];
    return next;
  };
  return (
    <fieldset>
      <legend>{label}</legend>
      <ol className="preference-order">
        {values.map((value, index) => (
          <li key={value}>
            <span>{names[value] || value}</span>
            <div>
              {onRemove && (
                <button
                  type="button"
                  aria-label={`Remove ${names[value] || value} from ${label}`}
                  disabled={values.length <= 1}
                  onClick={() => onRemove(value)}
                >
                  Remove
                </button>
              )}
              <button
                type="button"
                aria-label={`Move ${names[value] || value} up in ${label}`}
                disabled={index === 0 || !valid(moved(index, -1))}
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
                aria-label={`Move ${names[value] || value} down in ${label}`}
                disabled={
                  index === values.length - 1 || !valid(moved(index, 1))
                }
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
            </div>
          </li>
        ))}
      </ol>
    </fieldset>
  );
}
