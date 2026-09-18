import { EffectiveScope } from "./ScopeFields";
import RequestPreferences, { type Choice } from "./RequestPreferences";
import { EffectivePreferences } from "./PreferenceFields";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import { Link } from "react-router-dom";
import DownloadConstraints from "./DownloadConstraints";

type Spec = components["schemas"]["RequestOptions"];
export type WantedVersion = components["schemas"]["VersionView"];
const label = (slot: string) =>
  slot === "audio" ? "Audiobook" : slot === "ebook" ? "Ebook" : "Either medium";
const stateLabel = (state: string) =>
  ({
    wanted: "Wanted",
    satisfied: "Available",
    paused: "Paused",
    cancelled: "Cancelled",
    "awaiting-inventory": "Check inventory",
  })[state] || state;

export default function Wanted({
  workId,
  version,
  clearVersion,
}: {
  workId: string;
  version: WantedVersion | null;
  clearVersion: () => void;
}) {
  const cache = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [mode, setMode] = useState<Spec["mode"] | "">(
    version?.medium === "audio" || version?.medium === "ebook"
      ? version.medium
      : "",
  );
  const [preferred, setPreferred] = useState<"ebook" | "audio">("ebook");
  const [preferences, setPreferences] = useState<Choice>({});
  const [offset, setOffset] = useState(0);
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    if (version) heading.current?.focus();
  }, [version]);
  const specification: Spec = {
    ...(mode ? { mode } : {}),
    ...(mode === "either" ? { preferred_medium: preferred } : {}),
    ...(version?.medium === "audio" ? { audio_version_id: version.id } : {}),
    ...(version?.medium === "ebook" ? { ebook_version_id: version.id } : {}),
  };
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const selectedProfile = profiles.data?.find(
    (p) => (p.id || "") === (preferences.profile_id || ""),
  );
  const valid = !!(
    mode ||
    preferences.overrides?.desired_media ||
    selectedProfile?.preferences.desired_media
  );
  const preview = useQuery({
    queryKey: ["request-preview", workId, specification, preferences],
    queryFn: async () =>
      result(
        await api.POST("/api/requests/preview", {
          body: {
            work_id: workId,
            specification,
            release_preferences: preferences,
          },
        }),
      ),
    enabled: valid,
  });
  const requests = useQuery({
    queryKey: ["requests", workId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/requests", {
          params: { query: { work_id: workId, offset, limit: 10 } },
        }),
      ),
  });
  const refresh = async () => {
    await Promise.all(
      ["requests", "request-preview", "activity"].map((name) =>
        cache.invalidateQueries({ queryKey: [name] }),
      ),
    );
  };
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/requests", {
          body: {
            work_id: workId,
            specification,
            release_preferences: preferences,
            expected_preference_revision:
              preview.data?.release_policy?.effective_revision,
          },
          params: { header: { "idempotency-key": key.current } },
        }),
      ),
    onSuccess: async () => {
      key.current = crypto.randomUUID();
      await refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: async ({
      intent,
      reason,
    }: {
      intent: string;
      reason: string;
    }) =>
      result(
        await api.DELETE("/api/requests/{intent_id}/reasons/{reason_id}", {
          params: { path: { intent_id: intent, reason_id: reason } },
        }),
      ),
    onSuccess: refresh,
  });
  const changed = () => {
    key.current = crypto.randomUUID();
    save.reset();
  };
  return (
    <section className="panel editor library-access" aria-label="Wanted media">
      <h2 ref={heading} tabIndex={-1}>
        Wanted media
      </h2>
      <p className="muted">
        Track the media you want and skip copies already in your library. Save a
        request, then choose a source to acquire missing media.
      </p>
      {version ? (
        <div className="source-attribution">
          <span>
            <strong>{label(version.medium)} · Selected version</strong>
            <small>
              {version.narrators.join(", ") ||
                version.title ||
                "Selected edition"}
            </small>
          </span>
          <button type="button" onClick={clearVersion}>
            Choose any acceptable version
          </button>
        </div>
      ) : (
        <label>
          Media to request
          <select
            value={mode || ""}
            onChange={(event) => {
              changed();
              setMode(event.target.value as Spec["mode"]);
            }}
          >
            <option value="">Use profile or personal default</option>
            <option value="ebook">Ebook</option>
            <option value="audio">Audiobook</option>
            <option value="both">Both</option>
            <option value="either">Either</option>
          </select>
        </label>
      )}
      {mode === "either" && (
        <label>
          Search first when both are missing
          <select
            value={preferred}
            onChange={(event) => {
              changed();
              setPreferred(event.target.value as "ebook" | "audio");
            }}
          >
            <option value="ebook">Ebook</option>
            <option value="audio">Audiobook</option>
          </select>
          <small>
            Either existing medium satisfies this request. Compatible pending
            requests are reused first.
          </small>
        </label>
      )}
      <RequestPreferences
        value={preferences}
        onChange={(value) => {
          changed();
          setPreferences(value);
        }}
      />
      <Notice
        error={preview.error || save.error || requests.error || cancel.error}
      />
      {valid && preview.isPending && (
        <p className="muted">Checking your library…</p>
      )}
      {valid && preview.data && (
        <div aria-label="Request preview">
          <EffectiveScope
            specification={preview.data.specification}
            origins={preview.data.release_policy?.scope_origins}
          />
          {preview.data.release_policy && (
            <EffectivePreferences
              preferences={preview.data.release_policy.preferences}
              origins={preview.data.release_policy.origins || {}}
            />
          )}
          {preview.data.targets.map((target) => (
            <p key={target.slot}>
              <strong>
                {label(target.slot)} · {stateLabel(target.state)}
              </strong>
              <br />
              <span className="muted">{target.message}</span>
            </p>
          ))}
          {preview.data.series_scope &&
            preview.data.series_scope.state !== "single" && (
              <p>
                {preview.data.series_scope.message}. Complete this request from
                the reviewed series page, or choose Just this book in download
                preferences.
                {preview.data.series_scope.external_id && (
                  <>
                    <br />
                    <Link
                      to={`/series/hardcover/${preview.data.series_scope.external_id}`}
                    >
                      Open reviewed series
                    </Link>
                  </>
                )}
              </p>
            )}
        </div>
      )}
      <button
        className="primary"
        type="button"
        onClick={() => save.mutate()}
        disabled={
          !valid ||
          !preview.data ||
          preview.isFetching ||
          save.isPending ||
          Boolean(
            preview.data.series_scope &&
            preview.data.series_scope.state !== "single",
          )
        }
      >
        Save to wanted
      </button>
      {save.isSuccess && (
        <p className="success" role="status">
          Your media request was saved.
        </p>
      )}
      {!!requests.data?.items.length && (
        <>
          <h3>Your saved requests</h3>
          {requests.data.items.map((intent) => (
            <article className="panel editor" key={intent.id}>
              <p className="muted">{intent.description}</p>
              <EffectiveScope
                specification={intent.specification}
                origins={intent.release_policy?.scope_origins}
              />
              {intent.release_policy && (
                <EffectivePreferences
                  preferences={intent.release_policy.preferences}
                  origins={intent.release_policy.origins || {}}
                />
              )}
              <DownloadConstraints
                value={intent.specification.download_constraints}
              />
              {intent.targets.map((target) => (
                <p key={target.slot}>
                  <strong>
                    {label(target.slot)} · {stateLabel(target.state)}
                  </strong>
                  <br />
                  <span className="muted">{target.message}</span>
                  {target.state === "wanted" && (
                    <>
                      <br />
                      <Link
                        to={
                          target.source_artifact_id
                            ? `/sources/artifacts/${target.source_artifact_id}`
                            : `/books/${workId}?tab=sources&request=${intent.id}&slot=${target.slot}`
                        }
                      >
                        {target.source_artifact_id
                          ? "View selected release"
                          : "Choose a source release"}
                      </Link>
                    </>
                  )}
                </p>
              ))}
              {intent.reasons.map((reason) => (
                <div className="source-attribution" key={reason.id}>
                  <span>
                    {reason.label}
                    {reason.active ? "" : " · Cancelled"}
                  </span>
                  {reason.active && (
                    <button
                      type="button"
                      disabled={cancel.isPending}
                      onClick={() =>
                        cancel.mutate({ intent: intent.id, reason: reason.id })
                      }
                    >
                      Cancel {reason.label.toLowerCase()}
                    </button>
                  )}
                </div>
              ))}
            </article>
          ))}
          <div className="pagination">
            {offset > 0 && (
              <button type="button" onClick={() => setOffset(offset - 10)}>
                Previous requests
              </button>
            )}
            {offset + 10 < requests.data.total && (
              <button type="button" onClick={() => setOffset(offset + 10)}>
                Next requests
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
