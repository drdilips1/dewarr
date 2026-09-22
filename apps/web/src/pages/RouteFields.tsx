import SettingHelp from "../components/SettingHelp";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Preferences = components["schemas"]["ReleasePreferences"];
type Overrides = components["schemas"]["PreferenceOverrides"];
export const routeLabels = {
  torrent_downloader_id: "Default torrent downloader",
  usenet_downloader_id: "Default Usenet downloader",
  ebook_destination_id: "Default ebook destination",
  audio_destination_id: "Default audiobook destination",
} as const;
type Field = keyof typeof routeLabels;
type DownloaderChoice = { id: string; name: string; protocol?: string };

function protocolFor(field: Field) {
  if (field === "torrent_downloader_id") return "torrent";
  if (field === "usenet_downloader_id") return "nzb";
  return null;
}

export function protocolPreference(
  preferences: Partial<Preferences> | undefined,
  protocol: "torrent" | "nzb",
  downloaders: DownloaderChoice[] = [],
) {
  const specific =
    protocol === "torrent"
      ? preferences?.torrent_downloader_id
      : preferences?.usenet_downloader_id;
  if (specific) return specific;
  const legacy = preferences?.downloader_id;
  const client = downloaders.find((item) => item.id === legacy);
  return client?.protocol === protocol ? legacy : undefined;
}

export function primaryDownloaderPreference(
  preferences: Partial<Preferences> | undefined,
  downloaders: DownloaderChoice[] = [],
) {
  return (
    protocolPreference(preferences, "torrent", downloaders) ||
    protocolPreference(preferences, "nzb", downloaders)
  );
}

export function downloaderLabel(item: { name: string; protocol?: string }) {
  if (item.protocol === "nzb") return `${item.name} · Usenet`;
  if (item.protocol === "torrent") return `${item.name} · Torrents`;
  return item.name;
}

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
      <summary>
        <span className="setting-subheading">
          Downloader and destination defaults
          <SettingHelp label="download preferences">
            Defaults select where future acquisitions go. Automatic imports
            still require an approved, verified route. Saved requests keep their
            accepted choices.
          </SettingHelp>
        </span>
      </summary>

      <Notice error={options.error} />
      {(Object.keys(routeLabels) as Field[]).map((field) => {
        const protocol = protocolFor(field);
        const downloaders = options.data?.downloaders || [];
        const choices = protocol
          ? downloaders.filter((item) => item.protocol === protocol)
          : options.data?.destinations.filter(
              (d) =>
                d.medium ===
                (field === "audio_destination_id" ? "audio" : "ebook"),
            ) || [];
        const selected = protocol
          ? protocolPreference(values, protocol, downloaders) || ""
          : values[field] || "";
        return (
          <div key={field}>
            <label>
              {routeLabels[field]}
              <select
                aria-label={routeLabels[field]}
                value={selected}
                onChange={(event) => {
                  const raw = event.target.value;
                  const next = {
                    ...overrides,
                    [field]: raw || null,
                  };
                  if (
                    !raw &&
                    protocol &&
                    downloaders.find((item) => item.id === values.downloader_id)
                      ?.protocol === protocol
                  )
                    next.downloader_id = null;
                  onChange(next);
                }}
              >
                <option value="">No saved default</option>
                {selected && !choices.some((item) => item.id === selected) && (
                  <option value={selected}>Unavailable saved choice</option>
                )}
                {choices.map((item) => (
                  <option key={item.id} value={item.id}>
                    {protocol ? downloaderLabel(item) : item.name}
                    {item.ready ? "" : " · needs verification"}
                  </option>
                ))}
              </select>
            </label>
            {Object.hasOwn(overrides, field) && (
              <div className="preference-origin">
                <SettingHelp label="inherited value">
                  {Object.hasOwn(overrides, field)
                    ? "Custom value"
                    : `Inherited · ${origins[field] || "no default"}`}
                </SettingHelp>
                {Object.hasOwn(overrides, field) && (
                  <button
                    type="button"
                    aria-label={`Use inherited ${routeLabels[field]}`}
                    onClick={() => {
                      const next = { ...overrides };
                      delete next[field];
                      onChange(next);
                    }}
                  >
                    Reset
                  </button>
                )}
              </div>
            )}
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
  const options = useOptions(
    (Object.keys(routeLabels) as Field[]).some(
      (field) => preferences[field] || origins[field],
    ) || Boolean(preferences.downloader_id),
  );
  const downloaders = options.data?.downloaders || [];
  const fields = (Object.keys(routeLabels) as Field[]).filter((field) => {
    const protocol = protocolFor(field);
    return (
      preferences[field] ||
      origins[field] ||
      (protocol
        ? protocolPreference(preferences, protocol, downloaders)
        : undefined)
    );
  });
  if (!fields.length) return null;
  return (
    <dl>
      {fields.map((field) => {
        const protocol = protocolFor(field);
        const selected = protocol
          ? protocolPreference(preferences, protocol, downloaders)
          : preferences[field];
        const choices = protocol ? downloaders : options.data?.destinations;
        const name = selected
          ? protocol
            ? downloaderLabel(
                choices?.find((item) => item.id === selected) || {
                  name: "Unavailable saved choice",
                },
              )
            : choices?.find((item) => item.id === selected)?.name ||
              "Unavailable saved choice"
          : "No saved default";
        return (
          <div key={field}>
            <dt>{routeLabels[field]}</dt>
            <dd>
              {name}
              <small>
                {" "}
                · {origins[field] || origins.downloader_id || "Saved profile"}
              </small>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
