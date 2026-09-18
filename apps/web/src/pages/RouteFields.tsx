import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Preferences = components["schemas"]["ReleasePreferences"];
type Overrides = components["schemas"]["PreferenceOverrides"];
export const routeLabels = {
  downloader_id: "Default downloader",
  ebook_destination_id: "Default ebook destination",
  audio_destination_id: "Default audiobook destination",
} as const;
type Field = keyof typeof routeLabels;

export function chooseRoute<T extends { id: string }>(
  items: T[],
  selected?: string | null,
  preferred?: string | null,
) {
  const id = selected || preferred;
  return id
    ? items.find((item) => item.id === id)
    : items.length === 1
      ? items[0]
      : undefined;
}

export function destinationPreference(
  preferences: Partial<Preferences> | undefined,
  medium: string,
) {
  return medium === "audio"
    ? preferences?.audio_destination_id
    : preferences?.ebook_destination_id;
}

function useOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["selection-options"],
    enabled,
    queryFn: async () =>
      result(await api.GET("/api/acquisition/selections/options")),
  });
}

export default function RouteFields({
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
  const [open, setOpen] = useState(false);
  const options = useOptions(open);
  const values = { ...inherited, ...overrides };
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Downloader and destination defaults</summary>
      <p className="muted">
        Defaults select where future acquisitions go. Automatic imports still
        require an approved, verified route. Saved requests keep their accepted
        choices.
      </p>
      <Notice error={options.error} />
      {(Object.keys(routeLabels) as Field[]).map((field) => {
        const choices =
          field === "downloader_id"
            ? options.data?.downloaders || []
            : options.data?.destinations.filter(
                (d) =>
                  d.medium ===
                  (field === "audio_destination_id" ? "audio" : "ebook"),
              ) || [];
        return (
          <div key={field}>
            <label>
              {routeLabels[field]}
              <select
                aria-label={routeLabels[field]}
                value={values[field] || ""}
                onChange={(event) =>
                  onChange({
                    ...overrides,
                    [field]: event.target.value || null,
                  })
                }
              >
                <option value="">No saved default</option>
                {values[field] &&
                  !choices.some((item) => item.id === values[field]) && (
                    <option value={values[field]!}>
                      Unavailable saved choice
                    </option>
                  )}
                {choices.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                    {item.ready ? "" : " · needs verification"}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              {Object.hasOwn(overrides, field)
                ? "Custom value"
                : `Inherited · ${origins[field] || "no default"}`}
              {Object.hasOwn(overrides, field) && (
                <button
                  type="button"
                  onClick={() => {
                    const next = { ...overrides };
                    delete next[field];
                    onChange(next);
                  }}
                >
                  Use inherited {routeLabels[field]}
                </button>
              )}
            </p>
          </div>
        );
      })}
    </details>
  );
}

export function EffectiveRoutes({
  preferences,
  origins,
}: {
  preferences: Preferences;
  origins: Record<string, string>;
}) {
  const fields = (Object.keys(routeLabels) as Field[]).filter(
    (field) => preferences[field] || origins[field],
  );
  const options = useOptions(fields.length > 0);
  if (!fields.length) return null;
  return (
    <dl>
      {fields.map((field) => {
        const choices =
          field === "downloader_id"
            ? options.data?.downloaders
            : options.data?.destinations;
        return (
          <div key={field}>
            <dt>{routeLabels[field]}</dt>
            <dd>
              {preferences[field]
                ? choices?.find((item) => item.id === preferences[field])
                    ?.name || "Unavailable saved choice"
                : "No saved default"}
              <small> · {origins[field] || "Saved profile"}</small>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
