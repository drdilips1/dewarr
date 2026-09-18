import type { components } from "../api/schema";
type Preferences = components["schemas"]["ReleasePreferences"];
export type Overrides = components["schemas"]["PreferenceOverrides"];
export const preferenceLabels: Record<keyof Preferences, string> = {
  criteria: "Ranking priorities",
  source_order: "Source preference",
  ebook_formats: "Ebook format preference",
  audio_formats: "Audiobook format preference",
  blocked_formats: "Blocked formats",
  maximum_bytes: "Maximum transfer size",
};
const formats = [
  "epub",
  "pdf",
  "mobi",
  "azw",
  "azw3",
  "cbz",
  "cbr",
  "m4b",
  "mp3",
  "flac",
  "aac",
  "ogg",
  "opus",
];

function Order({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <fieldset>
      <legend>{label}</legend>
      <ol className="preference-order">
        {values.map((value, index) => (
          <li key={value}>
            <span>{value}</span>
            <div>
              <button
                type="button"
                aria-label={`Move ${value} up in ${label}`}
                disabled={index === 0}
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
                aria-label={`Move ${value} down in ${label}`}
                disabled={index === values.length - 1}
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

export default function PreferenceFields({
  overrides,
  inherited,
  origins,
  onChange,
}: {
  overrides: Overrides;
  inherited: Preferences;
  origins: Record<string, string>;
  onChange: (value: Overrides) => void;
}) {
  const effective = { ...inherited, ...overrides };
  const origin = (key: keyof Preferences) => (
    <p className="muted">
      {Object.hasOwn(overrides, key)
        ? "Custom value"
        : `Inherited · ${origins[key] || "default"}`}
      {Object.hasOwn(overrides, key) && (
        <button
          type="button"
          onClick={() => {
            const next = { ...overrides };
            delete next[key];
            onChange(next);
          }}
        >
          Use inherited {preferenceLabels[key]}
        </button>
      )}
    </p>
  );
  const order = (
    key: "criteria" | "source_order" | "ebook_formats" | "audio_formats",
  ) => (
    <div>
      <Order
        label={preferenceLabels[key]}
        values={effective[key] || []}
        onChange={(values) => onChange({ ...overrides, [key]: values })}
      />
      {origin(key)}
    </div>
  );
  return (
    <>
      <p className="muted">
        Change only what matters to you. Other values follow their defaults.
      </p>
      {order("criteria")}
      {order("source_order")}
      <details>
        <summary>Formats and transfer limits</summary>
        {order("ebook_formats")}
        {order("audio_formats")}
        <fieldset>
          <legend>Blocked formats</legend>
          {formats.map((format) => (
            <label className="check-label" key={format}>
              <input
                type="checkbox"
                checked={effective.blocked_formats?.includes(format) || false}
                onChange={(event) =>
                  onChange({
                    ...overrides,
                    blocked_formats: event.target.checked
                      ? [...(effective.blocked_formats || []), format]
                      : (effective.blocked_formats || []).filter(
                          (f) => f !== format,
                        ),
                  })
                }
              />
              {format.toUpperCase()}
            </label>
          ))}
        </fieldset>
        {origin("blocked_formats")}
        <label>
          Maximum transfer size (GiB, optional)
          <input
            type="number"
            min="0.01"
            max={Number.MAX_SAFE_INTEGER / 1024 ** 3}
            step="any"
            value={
              effective.maximum_bytes == null
                ? ""
                : effective.maximum_bytes / 1024 ** 3
            }
            onChange={(event) => {
              const bytes =
                event.target.value === ""
                  ? null
                  : Math.round(Number(event.target.value) * 1024 ** 3);
              if (bytes === null || (Number.isSafeInteger(bytes) && bytes > 0))
                onChange({ ...overrides, maximum_bytes: bytes });
            }}
          />
        </label>
        {origin("maximum_bytes")}
        <p className="muted">
          A blank custom limit means no profile size limit. Independent request
          restrictions and installation capacity limits still apply. Blocked
          formats apply to the whole transfer.
        </p>
      </details>
    </>
  );
}

export function EffectivePreferences({
  preferences,
  origins,
}: {
  preferences: Preferences;
  origins: Record<string, string>;
}) {
  return (
    <details>
      <summary>Effective download preferences</summary>
      <dl>
        {(Object.keys(preferenceLabels) as (keyof Preferences)[]).map((key) => (
          <div key={key}>
            <dt>{preferenceLabels[key]}</dt>
            <dd>
              {Array.isArray(preferences[key])
                ? (preferences[key] as string[]).join(" → ") || "None"
                : preferences[key] == null
                  ? "No profile limit"
                  : `${preferences[key]} bytes`}
              <small> · {origins[key] || "Saved profile"}</small>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
