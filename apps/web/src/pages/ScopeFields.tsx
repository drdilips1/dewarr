import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import NarratorNamesField from "./NarratorNamesField";
type Preferences = components["schemas"]["ReleasePreferences"];
type Overrides = components["schemas"]["PreferenceOverrides"];
type Spec = components["schemas"]["RequestSpec"];
export const scopeLabels = {
  desired_media: "Default requested media",
  preferred_medium: "Default first medium for Either",
  language: "Required language",
  abridged: "Audiobook abridgment",
  required_narrators: "Required narrators",
  standalone: "Standalone copies",
  ebook_library_id: "Ebook library",
  audio_library_id: "Audiobook library",
} as const;
const media = {
  ebook: "Ebook",
  audio: "Audiobook",
  both: "Both",
  either: "Either",
};
function useLibraries() {
  return useQuery({
    queryKey: ["libraries"],
    queryFn: async () => result(await api.GET("/api/library/libraries")),
  });
}
export default function ScopeFields({
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
  const libraries = useLibraries();
  const values = { ...inherited, ...overrides };
  const origin = (field: keyof typeof scopeLabels) => (
    <p className="muted">
      {Object.hasOwn(overrides, field)
        ? "Custom value"
        : `Inherited · ${origins[field] || "default"}`}
      {Object.hasOwn(overrides, field) && (
        <button
          type="button"
          onClick={() => {
            const next = { ...overrides };
            delete next[field];
            onChange(next);
          }}
        >
          Use inherited {scopeLabels[field]}
        </button>
      )}
    </p>
  );
  return (
    <details>
      <summary>Media, language and library defaults</summary>
      <p className="muted">
        Used when a request leaves the corresponding choice inherited. Existing
        requests keep their accepted scope. Library choices still require
        current access and a verified import route.
      </p>
      <Notice error={libraries.error} />
      {includeMedia && (
        <>
          <label>
            {scopeLabels.desired_media}
            <select
              value={values.desired_media || ""}
              onChange={(e) =>
                onChange({
                  ...overrides,
                  desired_media:
                    (e.target.value as Preferences["desired_media"]) || null,
                })
              }
            >
              <option value="">Choose on each request</option>
              {Object.entries(media).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {origin("desired_media")}
          <label>
            {scopeLabels.preferred_medium}
            <select
              value={values.preferred_medium}
              onChange={(e) =>
                onChange({
                  ...overrides,
                  preferred_medium: e.target.value as "ebook" | "audio",
                })
              }
            >
              <option value="audio">Audiobook</option>
              <option value="ebook">Ebook</option>
            </select>
          </label>
          {origin("preferred_medium")}
        </>
      )}
      <label>
        {scopeLabels.language}
        <input
          value={values.language || ""}
          placeholder="Any language"
          maxLength={20}
          pattern="[a-zA-Z]{2,3}([-_][a-zA-Z0-9]{2,8})*"
          onChange={(e) =>
            onChange({ ...overrides, language: e.target.value || null })
          }
        />
      </label>
      {origin("language")}
      <label>
        {scopeLabels.abridged}
        <select
          value={values.abridged == null ? "" : String(values.abridged)}
          onChange={(e) =>
            onChange({
              ...overrides,
              abridged:
                e.target.value === "" ? null : e.target.value === "true",
            })
          }
        >
          <option value="">Any abridgment</option>
          <option value="false">Unabridged only</option>
          <option value="true">Abridged only</option>
        </select>
      </label>
      {origin("abridged")}
      <NarratorNamesField
        label={scopeLabels.required_narrators}
        values={values.required_narrators || []}
        onChange={(required_narrators) =>
          onChange({ ...overrides, required_narrators })
        }
      />
      {origin("required_narrators")}
      <label className="check-label">
        <input
          type="checkbox"
          checked={values.standalone || false}
          onChange={(e) =>
            onChange({ ...overrides, standalone: e.target.checked })
          }
        />
        Require standalone copies
      </label>
      {origin("standalone")}
      {(["ebook_library_id", "audio_library_id"] as const).map((field) => (
        <div key={field}>
          <label>
            {scopeLabels[field]}
            <select
              value={values[field] || ""}
              onChange={(e) =>
                onChange({ ...overrides, [field]: e.target.value || null })
              }
            >
              <option value="">Choose during acquisition</option>
              {values[field] &&
                !libraries.data?.some((l) => l.id === values[field]) && (
                  <option value={values[field]!}>
                    Unavailable saved library
                  </option>
                )}
              {libraries.data
                ?.filter((l) => l.accessible)
                .map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
            </select>
          </label>
          {origin(field)}
        </div>
      ))}
    </details>
  );
}
export function EffectiveScope({
  specification,
  origins = {},
}: {
  specification: Spec;
  origins?: Record<string, string>;
}) {
  const libraries = useLibraries();
  const library = (id: string | null | undefined) =>
    id
      ? libraries.data?.find((l) => l.id === id)?.name ||
        "Unavailable saved library"
      : "Choose during acquisition";
  const rows = [
    ["mode", "Requested media", media[specification.mode]],
    ...(specification.mode === "either"
      ? [
          [
            "preferred_medium",
            "Search first",
            media[specification.preferred_medium || "audio"],
          ],
        ]
      : []),
    ["language", "Required language", specification.language || "Any language"],
    [
      "standalone",
      "Standalone copies",
      specification.standalone ? "Required" : "Omnibus allowed",
    ],
    ...(specification.mode !== "audio"
      ? [
          [
            "ebook_library_id",
            "Ebook library",
            library(specification.ebook_library_id),
          ],
        ]
      : []),
    ...(specification.mode !== "ebook"
      ? [
          [
            "audio_library_id",
            "Audiobook library",
            library(specification.audio_library_id),
          ],
          [
            "abridged",
            "Audiobook abridgment",
            specification.abridged == null
              ? "Any"
              : specification.abridged
                ? "Abridged"
                : "Unabridged",
          ],
          [
            "required_narrators",
            "Required narrators",
            specification.required_narrators?.join("; ") || "Any narrator",
          ],
        ]
      : []),
  ];
  return (
    <details>
      <summary>Effective request scope</summary>
      <dl>
        {rows.map(([key, label, value]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {value}
              <small> · {origins[key] || "Saved request"}</small>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
