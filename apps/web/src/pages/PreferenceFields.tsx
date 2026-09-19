import Order from "./PreferenceOrder";
import SourcePriorities from "./SourcePriorities";
import ScopeFields from "./ScopeFields";
import RouteFields, { EffectiveRoutes } from "./RouteFields";
import NarratorNamesField from "./NarratorNamesField";
import type { components } from "../api/schema";
type Preferences = components["schemas"]["ReleasePreferences"];
export type Overrides = components["schemas"]["PreferenceOverrides"];
export const preferenceLabels: Partial<Record<keyof Preferences, string>> = {
  allow_unknown_seeders: "Allow unknown seed counts",
  criteria: "Ranking priorities",
  source_order: "Source preference",
  ebook_formats: "Ebook format preference",
  audio_formats: "Audiobook format preference",
  blocked_formats: "Blocked formats",
  maximum_bytes: "Maximum transfer size",
  preferred_narrators: "Preferred narrators",
  search_series: "Search known series names",
  prefer_series_packs: "Prefer eligible series packs",
  series_scope: "Series scope",
};
export const seriesScopeLabels = {
  just_book: "Just this book",
  prefer_packs: "Prefer series packs",
  complete_series: "Complete reviewed series",
};
export function effectiveSeriesScope(
  preferences: Pick<Preferences, "series_scope" | "prefer_series_packs">,
) {
  return (
    preferences.series_scope ||
    (preferences.prefer_series_packs ? "prefer_packs" : "just_book")
  );
}
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
  if (
    Object.hasOwn(overrides, "prefer_series_packs") &&
    !Object.hasOwn(overrides, "series_scope")
  )
    delete effective.series_scope;
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
        valid={(values) =>
          key !== "criteria" ||
          !values.includes("popularity") ||
          values.indexOf("source") < values.indexOf("popularity")
        }
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
        <summary>Source popularity</summary>
        <p className="muted">
          Prefer higher completed-download counts within the same tracker.
          Currently MAM provides this count; other sources remain unknown.
          Source preference must come before popularity. Each tracker/indexer is
          grouped separately; equal source priorities use stable source IDs.
        </p>
        <button
          type="button"
          onClick={() => {
            const criteria = effective.criteria || [
              "format",
              "source",
              "seeders",
            ];
            if (criteria.includes("popularity"))
              onChange({
                ...overrides,
                criteria: criteria.filter((value) => value !== "popularity"),
              });
            else {
              const next = [...criteria];
              next.splice(next.indexOf("source") + 1, 0, "popularity");
              onChange({ ...overrides, criteria: next });
            }
          }}
        >
          {effective.criteria?.includes("popularity")
            ? "Stop ranking by popularity"
            : "Use source popularity in ranking"}
        </button>
      </details>
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
        <label>
          Series scope
          <select
            value={effectiveSeriesScope(effective)}
            onChange={(event) => {
              const next = {
                ...overrides,
                series_scope: event.target.value as NonNullable<
                  Overrides["series_scope"]
                >,
              };
              delete next.prefer_series_packs;
              onChange(next);
            }}
          >
            {Object.entries(seriesScopeLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {origin(
          effective.series_scope ? "series_scope" : "prefer_series_packs",
        )}
        <p className="muted">
          Known published series books and torrent filenames must agree. Up to
          20 additional books and 50 GiB per pack, subject to your lower size
          limit. Complete reviewed series lets automatic lists request a finite,
          saved main-book set. Manual complete-series requests use the series
          page. Prefer packs imports independently requested books from a
          qualifying pack.
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
      <SourcePriorities
        values={effective.source_order || []}
        onChange={(source_order) => onChange({ ...overrides, source_order })}
      />
      {origin("source_order")}
      <details>
        <summary>Unknown seed counts</summary>
        <label className="check-label">
          <input
            type="checkbox"
            checked={effective.allow_unknown_seeders ?? false}
            onChange={(event) =>
              onChange({
                ...overrides,
                allow_unknown_seeders: event.target.checked,
              })
            }
          />
          Allow AudiobookBay releases after torrent metadata resolves
        </label>
        <p className="muted">
          Off by default. Metadata resolution verifies the torrent manifest, not
          a seeder count or guaranteed payload availability. All identity,
          format, size and import checks still apply.
        </p>
        {origin("allow_unknown_seeders")}
      </details>
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
        {(Object.keys(preferenceLabels) as (keyof Preferences)[])
          .filter((key) => key !== "prefer_series_packs")
          .map((key) => (
            <div key={key}>
              <dt>{preferenceLabels[key]}</dt>
              <dd>
                {key === "series_scope"
                  ? seriesScopeLabels[effectiveSeriesScope(preferences)]
                  : Array.isArray(preferences[key])
                    ? (preferences[key] as string[]).join(" → ") || "None"
                    : typeof preferences[key] === "boolean"
                      ? preferences[key]
                        ? "Yes"
                        : "No"
                      : preferences[key] == null
                        ? "No profile limit"
                        : `${preferences[key]} bytes`}
                <small>
                  {" "}
                  ·{" "}
                  {origins[key] ||
                    (key === "series_scope" && origins.prefer_series_packs) ||
                    "Saved profile"}
                </small>
              </dd>
            </div>
          ))}
      </dl>
    </details>
  );
}
