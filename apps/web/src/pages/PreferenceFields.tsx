import ScopeFields from "./ScopeFields";
import RouteFields, { EffectiveRoutes } from "./RouteFields";
import NarratorNamesField from "./NarratorNamesField";
import type { components } from "../api/schema";
type Preferences = components["schemas"]["ReleasePreferences"];
export type Overrides = components["schemas"]["PreferenceOverrides"];
export const preferenceLabels: Partial<Record<keyof Preferences, string>> = {
  criteria: "Ranking priorities",
  source_order: "Source preference",
  ebook_formats: "Ebook format preference",
  audio_formats: "Audiobook format preference",
  blocked_formats: "Blocked formats",
  maximum_bytes: "Maximum transfer size",
  preferred_narrators: "Preferred narrators",
  search_series: "Search known series names",
  prefer_series_packs: "Prefer eligible series packs",
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
  includeMedia = true,
}: {
  overrides: Overrides;
  inherited: Preferences;
  origins: Record<string, string>;
  onChange: (value: Overrides) => void;
  includeMedia?: boolean;
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
        label={preferenceLabels[key]!}
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
      <ScopeFields
        overrides={overrides}
        inherited={inherited}
        origins={origins}
        onChange={onChange}
        includeMedia={includeMedia}
      />
      <RouteFields
        overrides={overrides}
        inherited={inherited}
        origins={origins}
        onChange={onChange}
      />
      {order("criteria")}
      <details>
        <summary>Series search</summary>
        <label className="check-label">
          <input
            type="checkbox"
            checked={effective.search_series ?? true}
            onChange={(event) =>
              onChange({ ...overrides, search_series: event.target.checked })
            }
          />
          Search known series names alongside the title
        </label>
        {origin("search_series")}
        <label className="check-label">
          <input
            type="checkbox"
            checked={effective.prefer_series_packs ?? true}
            onChange={(event) =>
              onChange({
                ...overrides,
                prefer_series_packs: event.target.checked,
              })
            }
          />
          Prefer eligible series packs
        </label>
        {origin("prefer_series_packs")}
        <p className="muted">
          Known published series books and torrent filenames must agree. Up to
          20 additional books and 50 GiB per pack, subject to your lower size
          limit. Only requested books are imported; this does not request an
          entire series.
        </p>
        <p className="muted">
          Searches up to three names from accessible catalog evidence. Finding a
          series release does not establish which books it contains.
        </p>
      </details>
      <details>
        <summary>Narrator preferences</summary>
        <NarratorNamesField
          label="Preferred narrators"
          ordered
          values={effective.preferred_narrators || []}
          onChange={(preferred_narrators) =>
            onChange({ ...overrides, preferred_narrators })
          }
        />
        {origin("preferred_narrators")}
        {!effective.criteria?.includes("narrator") ? (
          <>
            <p className="muted">
              Narrator preference breaks ties after the ranking priorities
              above.
            </p>
            <button
              type="button"
              onClick={() =>
                onChange({
                  ...overrides,
                  criteria: [
                    "narrator",
                    ...(effective.criteria || ["format", "source", "seeders"]),
                  ],
                })
              }
            >
              Rank narrator preference first
            </button>
          </>
        ) : (
          <>
            <p className="muted">
              Move narrator in Ranking priorities to choose when this preference
              applies.
            </p>
            <button
              type="button"
              onClick={() =>
                onChange({
                  ...overrides,
                  criteria: effective.criteria?.filter(
                    (criterion) => criterion !== "narrator",
                  ),
                })
              }
            >
              Use narrator preference only to break ties
            </button>
          </>
        )}
      </details>
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
      <EffectiveRoutes preferences={preferences} origins={origins} />
      <dl>
        {(Object.keys(preferenceLabels) as (keyof Preferences)[]).map((key) => (
          <div key={key}>
            <dt>{preferenceLabels[key]}</dt>
            <dd>
              {Array.isArray(preferences[key])
                ? (preferences[key] as string[]).join(" → ") || "None"
                : typeof preferences[key] === "boolean"
                  ? preferences[key]
                    ? "Yes"
                    : "No"
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
