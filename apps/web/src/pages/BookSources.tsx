import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import ReleaseProfiles from "./ReleaseProfiles";

const AutomaticSelection = lazy(() => import("./AutomaticSelection"));

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
  const [seriesSearch, setSeriesSearch] = useState("inherit");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const initial = useRef(false);
  const key = useRef(crypto.randomUUID());
  const requestId = params.get("request");
  const queryKey = ["book-sources", work.id, requestId];
  const request = useQuery({
    queryKey: ["source-request", requestId],
    enabled: !!requestId,
    queryFn: async () =>
      result(
        await api.GET("/api/requests/{intent_id}", {
          params: { path: { intent_id: requestId! } },
        }),
      ),
  });
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const search = useQuery({
    queryKey,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works/{work_id}/source-searches/latest", {
          params: {
            path: { work_id: work.id },
            query: { request_id: requestId || undefined },
          },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data && query.state.data.status !== "completed"
        ? 1500
        : false,
  });
  const chosen =
    profiles.data?.find(
      (p) =>
        (p.id || "") ===
        (selectedId ??
          (request.data?.release_policy
            ? request.data.release_policy.id || ""
            : (search.data?.profile.id ?? ""))),
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
            request_id: requestId,
            medium,
            offset,
            profile_id: chosen?.id,
            profile_generation: chosen?.generation,
            profile_effective_revision: chosen?.effective_revision,
            preference_overrides:
              seriesSearch === "inherit"
                ? undefined
                : { search_series: seriesSearch === "include" },
          },
        }),
      ),
    onSuccess: (value) => {
      key.current = crypto.randomUUID();
      cache.setQueryData(queryKey, value);
    },
  });
  useEffect(() => {
    if (
      search.isSuccess &&
      search.data &&
      (!requestId || search.data.request_id === requestId) &&
      !initial.current
    ) {
      initial.current = true;
      setQ(search.data.query);
      setMedium(search.data.medium);
    }
    if (
      search.isSuccess &&
      (search.data === null ||
        (!!requestId && search.data?.request_id !== requestId)) &&
      (!requestId || request.isSuccess) &&
      profiles.isSuccess &&
      !initial.current
    ) {
      initial.current = true;
      begin.mutate(0);
    }
  }, [
    search.isSuccess,
    search.data,
    profiles.isSuccess,
    requestId,
    request.isSuccess,
    begin,
  ]);
  const inspect = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.POST(
          "/api/source-searches/{search_id}/results/{result_id}/artifact",
          { params: { path: { search_id: search.data!.id, result_id: id } } },
        ),
      ),
    onSuccess: (artifact) => {
      const context = new URLSearchParams({
        work: work.id,
        search: search.data!.id,
      });
      if (search.data?.profile.id) {
        context.set("profile", search.data.profile.id);
        context.set(
          "profile_generation",
          String(search.data.profile.generation),
        );
      }
      if (search.data?.profile.effective_revision)
        context.set(
          "profile_effective_revision",
          search.data.profile.base_effective_revision ||
            search.data.profile.effective_revision,
        );
      for (const field of ["request", "slot"])
        if (params.get(field)) context.set(field, params.get(field)!);
      navigate(`/sources/artifacts/${artifact.id}?${context}`);
    },
  });
  const busy =
    begin.isPending ||
    inspect.isPending ||
    (search.data && search.data.status !== "completed");
  const data =
    !requestId || search.data?.request_id === requestId ? search.data : null;
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
        <Link to={`/sources/audiobookbay?q=${encodeURIComponent(work.title)}`}>
          AudiobookBay search and settings
        </Link>
      </div>
      <Notice
        error={
          search.error ||
          profiles.error ||
          request.error ||
          begin.error ||
          inspect.error
        }
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
          disabled={
            !!busy ||
            !profiles.data ||
            (!!requestId && !request.isSuccess) ||
            !q.trim()
          }
        >
          Refresh source results
        </button>
        <details>
          <summary>Search options</summary>
          <label>
            Series search
            <select
              value={seriesSearch}
              onChange={(event) => setSeriesSearch(event.target.value)}
            >
              <option value="inherit">Use inherited search preferences</option>
              <option value="include">Title and known series names</option>
              <option value="exclude">Entered query only</option>
            </select>
          </label>
        </details>
      </form>
      {chosen && canAcquire && (
        <ReleaseProfiles
          key={`${chosen.id}:${chosen.effective_revision}`}
          profile={chosen}
          defaults={profiles.data![0]}
          onSaved={(p) => setSelectedId(p.id || "")}
        />
      )}
      {data && (
        <Results
          key={data.id}
          data={data}
          inspecting={inspect.isPending}
          canAcquire={canAcquire}
          onInspect={(id) => inspect.mutate(id)}
        />
      )}
      {data &&
        canAcquire &&
        params.get("request") &&
        ["ebook", "audio", "either"].includes(params.get("slot") || "") && (
          <Suspense fallback={<p>Loading release preparation…</p>}>
            <AutomaticSelection
              key={`${params.get("request")}:${params.get("slot")}`}
              search={data}
              requestId={params.get("request")!}
              slot={params.get("slot")!}
            />
          </Suspense>
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
  const [pageIndex, setPageIndex] = useState(0);
  const [sort, setSort] = useState("profile");
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [format, setFormat] = useState("");
  const [hideBlocked, setHideBlocked] = useState(false);
  const resultsHeading = useRef<HTMLParagraphElement>(null);
  const origins = new Map(
    data.items.map(({ release }) => [sourceKey(release), sourceName(release)]),
  );
  const formats = [
    ...new Set(
      data.items.flatMap(({ release }) =>
        (release.formats || []).map((value) => value.toLowerCase()),
      ),
    ),
  ].sort();
  const needle = text.trim().toLowerCase();
  const filtered = data.items
    .map((item, rank) => ({ item, rank }))
    .filter(({ item }) => {
      const release = item.release;
      return (
        (!source || sourceKey(release) === source) &&
        (!format ||
          (format === "unknown"
            ? !release.formats?.length
            : release.formats?.some(
                (value) => value.toLowerCase() === format,
              ))) &&
        (!hideBlocked ||
          (item.current_connection && !item.assessment.blocked.length)) &&
        (!needle ||
          [
            release.title,
            release.raw_title,
            ...(release.authors || []),
            ...(release.narrators || []),
          ].some((value) => value.toLowerCase().includes(needle)))
      );
    });
  filtered.sort((a, b) => {
    let order = 0;
    if (sort === "seeds")
      order = compareKnown(
        a.item.release.seeders,
        b.item.release.seeders,
        true,
      );
    else if (sort === "smallest" || sort === "largest")
      order = compareKnown(
        a.item.release.size_bytes,
        b.item.release.size_bytes,
        sort === "largest",
      );
    else if (sort === "title")
      order = a.item.release.title.localeCompare(b.item.release.title);
    return order || a.rank - b.rank;
  });
  const filteredView = !!(needle || source || format || hideBlocked);
  const page = Math.min(
    pageIndex,
    Math.max(0, Math.ceil(filtered.length / 50) - 1),
  );
  const offset = page * 50;
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
          The catalog identity or series evidence changed. Refresh the search
          before inspecting a result.
        </p>
      )}
      {data.catalog_preparation && (
        <details>
          <summary>Series metadata · {data.catalog_preparation.state}</summary>
          <p>{data.catalog_preparation.message}</p>
          <ul>
            {data.catalog_preparation.items.map((item) => (
              <li key={item.external_id}>
                {item.name}: {item.message}
              </li>
            ))}
          </ul>
          {data.catalog_preparation.warnings.map((warning) => (
            <p className="notice" key={warning}>
              {warning}
            </p>
          ))}
        </details>
      )}
      {data.query_plan && (
        <details>
          <summary>Search queries ({data.query_plan.queries.length})</summary>
          <p className="muted">
            Series names broaden discovery. They do not confirm pack contents or
            authorize additional downloads.
          </p>
          {data.query_plan.queries.map((query) => (
            <div key={query.key}>
              <p>
                {query.kind === "series" ? "Series" : "Entered query"}:{" "}
                {query.query}
              </p>
              {query.evidence.map((evidence, index) => (
                <p className="muted" key={index}>
                  {evidence.provider} · {evidence.external_id} · observed{" "}
                  {new Date(evidence.observed_at).toLocaleString()}
                </p>
              ))}
            </div>
          ))}
          {data.query_plan.warnings.map((message) => (
            <p key={message} className="notice">
              {message}
            </p>
          ))}
        </details>
      )}
      <details>
        <summary>
          Source progress ·{" "}
          {data.sources.filter((source) => source.state === "completed").length}
          /{data.sources.length} complete
          {data.sources.some((source) => source.state === "failed")
            ? " · Some queries failed"
            : ""}
        </summary>
        <ul aria-label="Source search progress">
          {data.sources.map((source) => (
            <li key={source.key}>
              <strong>{source.name}</strong> · {source.state} · {source.count}{" "}
              results
              <p className="muted">
                {source.message}
                {source.query ? ` · “${source.query}”` : ""}
                {source.observed_at
                  ? ` · ${new Date(source.observed_at).toLocaleString()}`
                  : ""}
              </p>
            </li>
          ))}
        </ul>
      </details>
      {!data.sources.length && (
        <p className="notice">
          Connect MAM, AudiobookBay or Prowlarr to search for releases.
        </p>
      )}
      <p className="muted">
        Ranked with {data.profile.name}:{" "}
        {(data.profile.preferences.criteria || []).join(" → ")}. This ranks the
        fetched page, not every release on the trackers. Source claims require
        file inspection; no automatic download starts here.
      </p>
      {data.items.length > 0 && (
        <section
          className="panel release-comparison"
          aria-label="Compare loaded releases"
        >
          <div className="library-filters">
            <label className="grow">
              Filter title, author or narrator
              <input
                value={text}
                maxLength={300}
                onChange={(event) => {
                  setText(event.target.value);
                  setPageIndex(0);
                }}
              />
            </label>
            <label>
              Sort this view
              <select
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value);
                  setPageIndex(0);
                }}
              >
                <option value="profile">Profile ranking</option>
                <option value="seeds">Most seeders</option>
                <option value="smallest">Smallest download</option>
                <option value="largest">Largest download</option>
                <option value="title">Title A–Z</option>
              </select>
            </label>
          </div>
          <details>
            <summary>Filter loaded releases</summary>
            <div className="library-filters">
              <label>
                Result source
                <select
                  value={source}
                  onChange={(event) => {
                    setSource(event.target.value);
                    setPageIndex(0);
                  }}
                >
                  <option value="">All sources</option>
                  {[...origins].map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reported format
                <select
                  value={format}
                  onChange={(event) => {
                    setFormat(event.target.value);
                    setPageIndex(0);
                  }}
                >
                  <option value="">All formats</option>
                  {formats.map((value) => (
                    <option key={value} value={value}>
                      {value.toUpperCase()}
                    </option>
                  ))}
                  <option value="unknown">Unknown format</option>
                </select>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={hideBlocked}
                  onChange={(event) => {
                    setHideBlocked(event.target.checked);
                    setPageIndex(0);
                  }}
                />
                Hide blocked or expired results
              </label>
            </div>
          </details>
          <p className="muted">
            Only loaded results are compared. Unknown seeds and sizes sort last.
            View controls do not change your download profile or automatic
            selection.
          </p>
          {(filteredView || sort !== "profile") && (
            <button
              onClick={() => {
                setText("");
                setSource("");
                setFormat("");
                setHideBlocked(false);
                setSort("profile");
                setPageIndex(0);
              }}
            >
              Reset result view
            </button>
          )}
        </section>
      )}
      <p tabIndex={-1} ref={resultsHeading} aria-live="polite">
        {data.items.length} distinct releases
        {filteredView ? ` · ${filtered.length} match your filters` : ""}
        {filtered.length > 0
          ? ` · showing ${offset + 1}–${Math.min(offset + 50, filtered.length)}`
          : ""}
      </p>
      {filteredView && !filtered.length && (
        <p className="notice">
          No loaded releases match these filters. Clear the filters to see the
          other results.
        </p>
      )}
      {filtered.slice(offset, offset + 50).map(({ item, rank }) => (
        <article
          className="panel editor source-release"
          key={item.id}
          aria-label={item.release.title}
        >
          <div>
            <p className="eyebrow">
              {sourceName(item.release)} · Profile rank {rank + 1}
            </p>
            <h3>{item.release.title}</h3>
            {!!item.query_keys?.length && data.query_plan && (
              <p className="muted">
                Found by:{" "}
                {(item.query_keys || [])
                  .map(
                    (key) =>
                      data.query_plan?.queries.find(
                        (query) => query.key === key,
                      )?.query,
                  )
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
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
                  MAM completed downloads:{" "}
                  {item.release.snatches != null && item.release.snatches >= 0
                    ? item.release.snatches.toLocaleString()
                    : "Unknown"}
                  . This is a MAM-only popularity measure.
                </p>
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
                data.stale_identity ||
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
      {filtered.length > 50 && (
        <nav className="button-row" aria-label="Ranked release pages">
          <button
            disabled={page === 0 || inspecting}
            onClick={() => {
              setPageIndex(page - 1);
              resultsHeading.current?.focus();
              resultsHeading.current?.scrollIntoView({ block: "start" });
            }}
          >
            Previous releases
          </button>
          <button
            disabled={offset + 50 >= filtered.length || inspecting}
            onClick={() => {
              setPageIndex(page + 1);
              resultsHeading.current?.focus();
              resultsHeading.current?.scrollIntoView({ block: "start" });
            }}
          >
            Next releases
          </button>
        </nav>
      )}
    </>
  );
}

function sourceKey(release: Search["items"][number]["release"]) {
  return release.source === "prowlarr"
    ? `prowlarr:${release.indexer_id}`
    : release.source;
}

function sourceName(release: Search["items"][number]["release"]) {
  return release.source === "mam"
    ? "MAM"
    : release.source === "audiobookbay"
      ? "AudiobookBay"
      : `${release.indexer_name || "Prowlarr"} (indexer ${release.indexer_id})`;
}

function compareKnown(
  a: number | null | undefined,
  b: number | null | undefined,
  descending: boolean,
) {
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  return descending ? b - a : a - b;
}
