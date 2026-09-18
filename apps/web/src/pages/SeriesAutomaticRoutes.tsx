import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import type { Choice } from "./RequestPreferences";

export function useSeriesRoutes(
  enabled: boolean,
  requested: string | null | undefined,
  choice: Choice,
) {
  const [downloaderId, setDownloaderId] = useState("");
  const [destinations, setDestinations] = useState<Record<string, string>>({});
  const options = useQuery({
    queryKey: ["selection-options"],
    enabled,
    queryFn: async () =>
      result(await api.GET("/api/acquisition/selections/options")),
  });
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    enabled,
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const profile = profiles.data?.find(
    (p) => (p.id || "") === (choice.profile_id || ""),
  );
  const mode =
    requested ||
    choice.overrides?.desired_media ||
    profile?.preferences.desired_media;
  const media =
    mode === "both" || mode === "either"
      ? ["ebook", "audio"]
      : mode
        ? [mode]
        : [];
  const downloaders = options.data?.downloaders.filter((d) => d.ready) || [];
  const downloader =
    downloaders.find((d) => d.id === downloaderId) ||
    (downloaders.length === 1 ? downloaders[0] : undefined);
  const available = (medium: string) =>
    options.data?.destinations.filter(
      (d) =>
        d.medium === medium &&
        d.ready &&
        d.automatic_import_ready &&
        d.source_key === downloader?.source_key,
    ) || [];
  const destination = (medium: string) =>
    available(medium).find((d) => d.id === destinations[medium]) ||
    (available(medium).length === 1 ? available(medium)[0] : undefined);
  const routes = Object.fromEntries(
    media
      .filter((m) => destination(m))
      .map((m) => [
        m,
        {
          destination_id: destination(m)!.id,
          destination_revision: destination(m)!.revision,
        },
      ]),
  );
  const input: components["schemas"]["AutomaticRoutes"] | undefined =
    downloader && media.length && Object.keys(routes).length === media.length
      ? {
          downloader_id: downloader.id,
          downloader_generation: downloader.generation,
          routes,
        }
      : undefined;
  return {
    input,
    options,
    profiles,
    media,
    downloaders,
    downloader,
    available,
    destination,
    setDownloaderId,
    setDestinations,
  };
}

export default function SeriesAutomaticRoutes({
  selection,
}: {
  selection: ReturnType<typeof useSeriesRoutes>;
}) {
  const {
    options,
    profiles,
    media,
    downloaders,
    downloader,
    available,
    destination,
    setDownloaderId,
    setDestinations,
  } = selection;
  return (
    <fieldset className="editor">
      <legend>Automatic series acquisition</legend>
      <Notice error={options.error || profiles.error} />
      <p>
        Search for missing requested media, download eligible releases, and
        import the reviewed books. Existing library items are skipped. Future
        series additions are not included.
      </p>
      {!media.length && (
        <p>Choose the requested media above or save a media default.</p>
      )}
      <label>
        Series downloader
        <select
          value={downloader?.id || ""}
          onChange={(event) => setDownloaderId(event.target.value)}
        >
          <option value="">Choose a tested downloader</option>
          {downloaders.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {media.map((medium) => (
        <label key={medium}>
          {medium === "audio" ? "Audiobook" : "Ebook"} series destination
          <select
            value={destination(medium)?.id || ""}
            onChange={(event) =>
              setDestinations((current) => ({
                ...current,
                [medium]: event.target.value,
              }))
            }
          >
            <option value="">Choose an approved destination</option>
            {available(medium).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      ))}
      <p className="muted">
        Only tested downloaders and administrator-approved import routes are
        offered. Reusable profiles control format and source ranking.
      </p>
    </fieldset>
  );
}
