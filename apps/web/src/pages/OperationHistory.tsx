import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Clock, CircleAlert } from "lucide-react";
import { api, result } from "../api/client";
import { Empty, Loading, Notice } from "../components";

const labels: Record<string, string> = {
  "acquisition.auto-select": "Automatic release preparation",
  "lists.requests": "List wanted media",
  "lists.csv": "CSV list import",
  "lists.sync": "External list observation",
  "lists.curate": "List curation",
  "lists.writeback": "Hardcover list write-back",
  "lists.writeback.compare": "Hardcover list comparison",
  "discovery.follow-list": "Follow community list",
  "sources.search": "Book source search",
  "system.probe": "Background worker check",
  "organization.automatic": "Automatic library import",
  "library.sync": "Audiobookshelf inventory sync",
  "acquisition.evaluate": "Wanted media check",
  "acquisition.download": "Book download",
  "acquisition.repair": "Download connection repair",
  "acquisition.review": "Download import review",
  "acquisition.select": "Release selection",
  "metadata.enrich": "Automatic metadata lookup",
  "metadata.resolve-import": "Imported metadata lookup",
};

export default function OperationHistory() {
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") || "").slice(0, 300);
  const status = (params.get("status") || "").slice(0, 40);
  const kind = (params.get("kind") || "").slice(0, 60);
  const rawOffset = Number(params.get("offset") || 0);
  const offset =
    Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  const cache = useQueryClient();
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  }
  const activity = useQuery({
    queryKey: ["activity", "history", q, status, kind, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/activity/page", {
          params: { query: { q, status, kind, offset, limit: 25 } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["queued", "running", "retrying"].includes(item.status),
      )
        ? 2000
        : 15000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (
      !activity.error &&
      activity.data?.items.some(
        (item) => item.kind === "library.sync" && item.status === "completed",
      )
    ) {
      for (const key of [
        "assets",
        "catalog",
        "work",
        "works",
        "requests",
        "request-preview",
        "libraries",
        "connections",
      ]) {
        void cache.invalidateQueries({ queryKey: [key] });
      }
    }
  }, [activity.data, activity.error, cache]);
  const filtered = Boolean(q || status || kind);
  const kinds = Array.from(
    new Set([
      ...(activity.error ? [] : activity.data?.kinds || []),
      ...(kind ? [kind] : []),
    ]),
  ).sort();
  const statuses = Array.from(
    new Set([
      ...(activity.error ? [] : activity.data?.statuses || []),
      ...(status ? [status] : []),
    ]),
  ).sort();
  return (
    <section
      className="operation-history"
      aria-labelledby="operation-history-title"
    >
      <h2 id="operation-history-title">Background activity</h2>
      <p className="muted">
        Your operation history, newest first. Filters apply to this history;
        requests and downloads above have their own status.
      </p>
      <form
        className="library-search"
        aria-label="Search background activity"
        onSubmit={(event) => {
          event.preventDefault();
          change(
            "q",
            String(new FormData(event.currentTarget).get("q") || "").trim(),
          );
        }}
      >
        <label>
          Search activity
          <input
            key={q}
            name="q"
            type="search"
            maxLength={300}
            defaultValue={q}
            placeholder="Message, task type or operation ID"
          />
        </label>
        <button type="submit">Search activity</button>
      </form>
      <div className="library-filters">
        <label>
          Activity status
          <select
            value={status}
            onChange={(event) => change("status", event.target.value)}
          >
            <option value="">All statuses</option>
            {statuses.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Task type
          <select
            value={kind}
            onChange={(event) => change("kind", event.target.value)}
          >
            <option value="">All task types</option>
            {kinds.map((value) => (
              <option key={value} value={value}>
                {labels[value] || value}
              </option>
            ))}
          </select>
        </label>
        {(filtered || offset > 0) && (
          <button
            type="button"
            onClick={() => {
              const next = new URLSearchParams(params);
              for (const key of ["q", "status", "kind", "offset"])
                next.delete(key);
              setParams(next);
            }}
          >
            Reset activity view
          </button>
        )}
      </div>
      <Notice error={activity.error} />
      {activity.isPending && <Loading />}
      {activity.error && (
        <button
          disabled={activity.isFetching}
          onClick={() => activity.refetch()}
        >
          Retry activity
        </button>
      )}
      {!activity.error && activity.data && (
        <>
          <p className="muted" role="status">
            {activity.data.total} matching{" "}
            {activity.data.total === 1 ? "operation" : "operations"}
          </p>
          {activity.data.items.length ? (
            <div className="activity-list">
              {activity.data.items.map((item) => (
                <article
                  className="activity-row"
                  key={item.id}
                  aria-label={`${labels[item.kind] || item.kind}: ${item.status}`}
                >
                  <div
                    className={
                      item.status === "completed"
                        ? "activity-icon success"
                        : "activity-icon"
                    }
                    aria-hidden="true"
                  >
                    {item.status === "completed" ? (
                      <Check size={20} />
                    ) : ["failed", "attention", "blocked"].includes(
                        item.status,
                      ) ? (
                      <CircleAlert size={20} />
                    ) : (
                      <Clock size={20} />
                    )}
                  </div>
                  <div className="grow">
                    <h3>{labels[item.kind] || item.kind}</h3>
                    <p>{item.message}</p>
                    {item.context && (
                      <Link className="back-link" to={item.context.href}>
                        {item.context.label}
                      </Link>
                    )}
                    <details className="operation-details">
                      <summary>Operation details</summary>
                      <p>
                        Operation ID: <code>{item.id}</code>
                      </p>
                      <p>
                        Last updated:{" "}
                        <time dateTime={item.updated_at}>
                          {new Date(item.updated_at).toLocaleString()}
                        </time>
                      </p>
                    </details>
                  </div>
                  <div className="activity-meta">
                    <span className="status">{item.status}</span>
                    <time dateTime={item.created_at}>
                      {new Date(item.created_at).toLocaleString()}
                    </time>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title={
                filtered
                  ? "No matching activity"
                  : "No background activity on this page"
              }
            >
              {offset > 0
                ? "Go back to an earlier page or reset the view."
                : filtered
                  ? "Try another search or reset the filters."
                  : "Your requests and background checks will appear here."}
            </Empty>
          )}
          {(offset > 0 || activity.data.total > 25) && (
            <div className="pagination" aria-label="Activity history pages">
              <button
                disabled={offset === 0 || activity.isFetching}
                onClick={() =>
                  change("offset", String(Math.max(0, offset - 25)))
                }
              >
                Previous activity
              </button>
              <span>Page {Math.floor(offset / 25) + 1}</span>
              <button
                disabled={
                  offset + 25 >= activity.data.total || activity.isFetching
                }
                onClick={() => change("offset", String(offset + 25))}
              >
                Next activity
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
