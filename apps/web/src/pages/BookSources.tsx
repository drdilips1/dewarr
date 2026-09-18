import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import ReleaseProfiles from "./ReleaseProfiles";

type Work = components["schemas"]["WorkView"];
type Search = components["schemas"]["BookSearchView"];

export default function BookSources({
  work,
  canAcquire,
}: {
  work: Work;
  canAcquire: boolean;
}) {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [q, setQ] = useState(work.title.slice(0, 300));
  const [medium, setMedium] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const initial = useRef(false);
  const key = useRef(crypto.randomUUID());
  const queryKey = ["book-sources", work.id];
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const search = useQuery({
    queryKey,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works/{work_id}/source-searches/latest", {
          params: { path: { work_id: work.id } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data && query.state.data.status !== "completed"
        ? 1500
        : false,
  });
  const chosen =
    profiles.data?.find(
      (p) => (p.id || "") === (selectedId ?? search.data?.profile.id ?? ""),
    ) || profiles.data?.[0];
  const begin = useMutation({
    mutationFn: async (offset: number) =>
      result(
        await api.POST("/api/catalog/works/{work_id}/source-searches", {
          params: {
            path: { work_id: work.id },
            header: { "idempotency-key": key.current },
          },
          body: {
            q,
            medium,
            offset,
            profile_id: chosen?.id,
            profile_generation: chosen?.generation,
          },
        }),
      ),
    onSuccess: (value) => {
      key.current = crypto.randomUUID();
      cache.setQueryData(queryKey, value);
    },
  });
  useEffect(() => {
    if (search.isSuccess && search.data && !initial.current) {
      initial.current = true;
      setQ(search.data.query);
      setMedium(search.data.medium);
    }
    if (
      search.isSuccess &&
      search.data === null &&
      profiles.isSuccess &&
      !initial.current
    ) {
      initial.current = true;
      begin.mutate(0);
    }
  }, [search.isSuccess, search.data, profiles.isSuccess, begin]);
  const inspect = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.POST(
          "/api/source-searches/{search_id}/results/{result_id}/artifact",
          { params: { path: { search_id: search.data!.id, result_id: id } } },
        ),
      ),
    onSuccess: (artifact) => {
      const context = new URLSearchParams({ work: work.id });
      if (search.data?.profile.id) {
        context.set("profile", search.data.profile.id);
        context.set(
          "profile_generation",
          String(search.data.profile.generation),
        );
      }
      for (const field of ["request", "slot"])
        if (params.get(field)) context.set(field, params.get(field)!);
      navigate(`/sources/artifacts/${artifact.id}?${context}`);
    },
  });
  const busy =
    begin.isPending ||
    inspect.isPending ||
    (search.data && search.data.status !== "completed");
  const data = search.data;
  return (
    <section aria-label="Book download sources">
      <h2>Download sources</h2>
      <p>
        Compare releases for this title. Your catalog editions and library
        availability stay separate.
      </p>
      <div className="button-row">
        <Link to={`/sources?q=${encodeURIComponent(work.title)}`}>
          Direct MAM search and settings
        </Link>
        <Link to={`/sources/prowlarr?q=${encodeURIComponent(work.title)}`}>
          Prowlarr search and settings
        </Link>
      </div>
      <Notice
        error={search.error || profiles.error || begin.error || inspect.error}
      />
      <form
        className="panel editor"
        onSubmit={(event) => {
          event.preventDefault();
          key.current = crypto.randomUUID();
          begin.mutate(0);
        }}
      >
        <label>
          Release search query
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            required
            maxLength={300}
          />
        </label>
        <label>
          Release medium
          <select
            value={medium}
            onChange={(event) => setMedium(event.target.value)}
          >
            <option value="all">Ebook and audiobook</option>
            <option value="ebook">Ebook</option>
            <option value="audio">Audiobook</option>
          </select>
        </label>
        <label>
          Download profile
          <select
            value={chosen?.id || ""}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {profiles.data?.map((p) => (
              <option key={p.id || "balanced"} value={p.id || ""}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={!!busy || !profiles.data || !q.trim()}
        >
          Refresh source results
        </button>
      </form>
      {chosen && canAcquire && (
        <ReleaseProfiles
          key={`${chosen.id}:${chosen.generation}`}
          profile={chosen}
          onSaved={(p) => setSelectedId(p.id || "")}
        />
      )}
      {data && (
        <Results
          data={data}
          inspecting={inspect.isPending}
          canAcquire={canAcquire}
          onInspect={(id) => inspect.mutate(id)}
        />
      )}
      {data?.sources.some((source) => source.has_more) && (
        <button
          disabled={!!busy || data.offset >= 10000}
          onClick={() => {
            key.current = crypto.randomUUID();
            begin.mutate(data.offset + 50);
          }}
        >
          Next source page
        </button>
      )}
    </section>
  );
}

function Results({
  data,
  inspecting,
  canAcquire,
  onInspect,
}: {
  data: Search;
  inspecting: boolean;
  canAcquire: boolean;
  onInspect: (id: string) => void;
}) {
  return (
    <>
      <p role="status">{data.message}</p>
      <p>
        Results for “{data.query}” ·{" "}
        {data.medium === "all" ? "ebook and audiobook" : data.medium} · page{" "}
        {Math.floor(data.offset / 50) + 1}
      </p>
      {data.stale_identity && (
        <p className="notice error">
          The catalog identity changed. Refresh the search before inspecting a
          result.
        </p>
      )}
      <ul aria-label="Source search progress">
        {data.sources.map((source) => (
          <li key={source.key}>
            <strong>{source.name}</strong> · {source.state} · {source.count}{" "}
            results
            <p className="muted">
              {source.message}
              {source.observed_at
                ? ` · ${new Date(source.observed_at).toLocaleString()}`
                : ""}
            </p>
          </li>
        ))}
      </ul>
      {!data.sources.length && (
        <p className="notice">
          Connect MAM or Prowlarr to search for releases.
        </p>
      )}
      <p className="muted">
        Ranked with {data.profile.name}:{" "}
        {(data.profile.preferences.criteria || []).join(" → ")}. This ranks the
        fetched page, not every release on the trackers. Source claims require
        file inspection; no automatic download starts here.
      </p>
      {data.items.map((item) => (
        <article
          className="panel editor source-release"
          key={item.id}
          aria-label={item.release.title}
        >
          <div>
            <p className="eyebrow">
              {item.release.source === "mam"
                ? "MAM"
                : item.release.indexer_name}
            </p>
            <h3>{item.release.title}</h3>
            <p>
              {(item.release.authors || []).join(", ") || "Author not supplied"}
            </p>
          </div>
          <p>
            {item.release.medium || "Unknown medium"} ·{" "}
            {(item.release.formats || []).join(", ") || "Unknown format"} ·{" "}
            {item.release.seeders == null
              ? "Unknown seeds"
              : `${item.release.seeders} seeders`}{" "}
            ·{" "}
            {item.release.size_bytes == null
              ? "Unknown size"
              : `${item.release.size_bytes.toLocaleString()} bytes`}
          </p>
          {(item.release.narrators || []).length > 0 && (
            <p>Narrated by {(item.release.narrators || []).join(", ")}</p>
          )}
          {item.assessment.blocked.map((message) => (
            <p key={message} className="notice error">
              {message}
            </p>
          ))}
          {item.assessment.review.map((message) => (
            <p key={message} className="muted">
              {message}
            </p>
          ))}
          {!item.current_connection && (
            <p className="notice">
              This result expired or its source changed. Refresh the search.
            </p>
          )}
          <details>
            <summary>Why this ranking?</summary>
            <ul>
              {item.assessment.explanation.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </details>
          <details>
            <summary>Original release details</summary>
            <p className="source-description">
              {item.release.description || "No description supplied"}
            </p>
            <p>Raw title: {item.release.raw_title}</p>
            {item.release.source === "mam" && (
              <>
                <p>
                  Series:{" "}
                  {(item.release.series || [])
                    .map((s) => `${s.name} ${s.position || ""}`)
                    .join(", ") || "Unknown"}
                </p>
                <p>
                  Tags:{" "}
                  {(item.release.tags || []).join(", ") || "None supplied"}
                </p>
                <p className="source-description">{item.release.media_info}</p>
              </>
            )}
          </details>
          {canAcquire && (
            <button
              disabled={
                inspecting ||
                !item.current_connection ||
                item.assessment.blocked.length > 0
              }
              onClick={() => onInspect(item.id)}
            >
              Inspect this release
            </button>
          )}
        </article>
      ))}
    </>
  );
}
