import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Spec = components["schemas"]["RequestSpec"];
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
  const [language, setLanguage] = useState("");
  const [standalone, setStandalone] = useState(false);
  const [offset, setOffset] = useState(0);
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    if (version) heading.current?.focus();
  }, [version]);
  const specification: Spec = {
    mode: mode || "ebook",
    preferred_medium: mode === "either" ? preferred : null,
    language: language || null,
    standalone,
    ...(version?.medium === "audio" ? { audio_version_id: version.id } : {}),
    ...(version?.medium === "ebook" ? { ebook_version_id: version.id } : {}),
  };
  const valid =
    !!mode &&
    (!language || /^[a-zA-Z]{2,3}([-_][a-zA-Z0-9]{2,8})*$/.test(language));
  const preview = useQuery({
    queryKey: ["request-preview", workId, specification],
    queryFn: async () =>
      result(
        await api.POST("/api/requests/preview", {
          body: { work_id: workId, specification },
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
          body: { work_id: workId, specification },
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
        Track the media you want and skip copies already in your library.
        Automatic downloading is not available yet.
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
            value={mode}
            onChange={(event) => {
              changed();
              setMode(event.target.value as Spec["mode"]);
            }}
          >
            <option value="">Choose media</option>
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
      <details>
        <summary>Request preferences</summary>
        <label>
          Required language code
          <input
            value={language}
            placeholder="Any language"
            maxLength={20}
            onChange={(event) => {
              changed();
              setLanguage(event.target.value);
            }}
          />
          <small>
            For example, en for English. An unknown language will not satisfy a
            required language.
          </small>
        </label>
        <label>
          <input
            type="checkbox"
            checked={standalone}
            onChange={(event) => {
              changed();
              setStandalone(event.target.checked);
            }}
          />
          Require a standalone copy rather than an omnibus
        </label>
      </details>
      <Notice
        error={preview.error || save.error || requests.error || cancel.error}
      />
      {valid && preview.isPending && (
        <p className="muted">Checking your library…</p>
      )}
      {valid && preview.data && (
        <div aria-label="Request preview">
          {preview.data.targets.map((target) => (
            <p key={target.slot}>
              <strong>
                {label(target.slot)} · {stateLabel(target.state)}
              </strong>
              <br />
              <span className="muted">{target.message}</span>
            </p>
          ))}
        </div>
      )}
      <button
        className="primary"
        type="button"
        onClick={() => save.mutate()}
        disabled={
          !valid || !preview.data || preview.isFetching || save.isPending
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
              {intent.targets.map((target) => (
                <p key={target.slot}>
                  <strong>
                    {label(target.slot)} · {stateLabel(target.state)}
                  </strong>
                  <br />
                  <span className="muted">{target.message}</span>
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
