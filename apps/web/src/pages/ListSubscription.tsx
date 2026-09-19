import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import ListWriteback from "./ListWriteback";

type Subscription = components["schemas"]["SubscriptionView"];
type Observation = components["schemas"]["ObservationView"];

export default function ListSubscription({ listId }: { listId: string }) {
  const cache = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [choice, setChoice] = useState<"goodreads" | "hardcover">("goodreads");
  const key = useRef(crypto.randomUUID());
  const path = { list_id: listId };
  const subscription = useQuery({
    queryKey: ["list-subscription", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/subscription", {
          params: { path },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data && ["queued", "running"].includes(query.state.data.state)
        ? 1500
        : 30_000,
  });
  const observations = useQuery({
    queryKey: ["list-observations", listId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/subscription/observations", {
          params: { path, query: { offset, limit: 20 } },
        }),
      ),
    enabled: expanded && !!subscription.data,
  });
  const lastSuccess = subscription.data?.last_success_at;
  useEffect(() => {
    if (!lastSuccess) return;
    cache.invalidateQueries({ queryKey: ["list", listId] });
    cache.invalidateQueries({ queryKey: ["lists"] });
    cache.invalidateQueries({ queryKey: ["list-observations", listId] });
  }, [lastSuccess, listId, cache]);
  const refresh = () => {
    for (const queryKey of [
      ["list-subscription", listId],
      ["list-observations", listId],
      ["list", listId],
      ["lists"],
      ["catalog"],
    ])
      cache.invalidateQueries({ queryKey });
  };
  const sync = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/subscription/sync", {
          params: { path, header: { "idempotency-key": key.current } },
        }),
      ),
    onSuccess: () => {
      key.current = crypto.randomUUID();
      refresh();
    },
  });
  const save = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const fields = new FormData(form);
      const saved = result(
        await api.PUT("/api/lists/{list_id}/subscription", {
          params: { path },
          body: {
            provider: String(fields.get("provider")) as
              "goodreads" | "hardcover",
            hardcover_list_id: fields.get("hardcover_id")
              ? Number(fields.get("hardcover_id"))
              : null,
            feed_url: String(fields.get("url") || "") || null,
            interval_minutes: Number(fields.get("interval")),
            enabled: fields.get("enabled") === "on",
            expected_generation: subscription.data?.generation || 0,
          },
        }),
      );
      form.reset();
      return saved;
    },
    onSuccess: (saved) => {
      cache.setQueryData(["list-subscription", listId], saved);
      if (saved.enabled) sync.mutate();
    },
  });
  const detach = useMutation({
    mutationFn: async () =>
      result(
        await api.DELETE("/api/lists/{list_id}/subscription", {
          params: { path },
        }),
      ),
    onSuccess: () => {
      setExpanded(false);
      refresh();
    },
  });
  const data = subscription.data;
  const provider = data?.provider || choice;
  const hardcover = provider === "hardcover";
  const busy =
    sync.isPending || data?.state === "queued" || data?.state === "running";
  return (
    <section
      className="panel editor"
      aria-label={
        hardcover
          ? "Hardcover list subscription"
          : "Goodreads shelf subscription"
      }
    >
      <h2>
        {hardcover ? "Follow a Hardcover list" : "Follow a Goodreads shelf"}
      </h2>
      <p>
        {hardcover
          ? "Follow your own or an accessible community list. Verified removals affect source-only entries; books you added locally stay here."
          : "Bring shelf additions into this list. Books missing from a later feed stay here."}{" "}
        Removing an imported book excludes it from future refreshes.
      </p>
      <p className="muted">
        Shelf sync updates list membership. Download behavior is controlled by
        this list’s acquisition policy; reading status stays unchanged.
      </p>
      <Notice
        error={subscription.error || save.error || sync.error || detach.error}
      />
      {data && (
        <>
          <p role="status">{data.message}</p>
          <p>
            {data.provider === "hardcover"
              ? `${data.present_count} currently listed`
              : `${data.observed_count} observed`}{" "}
            · {data.excluded_count} excluded · {data.shelf}
          </p>
          <p className="muted">
            Last success:{" "}
            {data.last_success_at
              ? new Date(data.last_success_at).toLocaleString()
              : "Not yet observed"}
            .{" "}
            {hardcover
              ? "Only a fully verified observation updates membership."
              : "RSS is a partial view of a shelf."}
          </p>
          <button
            disabled={!!busy || !data.enabled}
            onClick={() => sync.mutate()}
          >
            {hardcover ? "Refresh Hardcover list" : "Refresh Goodreads shelf"}
          </button>
        </>
      )}
      {subscription.isSuccess && (
        <SubscriptionSettings
          key={data?.generation || "new"}
          data={data}
          pending={save.isPending}
          provider={provider}
          onProvider={setChoice}
          onSave={(form) => save.mutate(form)}
        />
      )}
      {data && (
        <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
          <summary>Observed entries and exclusions</summary>
          <Notice error={observations.error} />
          {expanded &&
            observations.data?.items.map((entry) => (
              <ObservedEntry
                key={entry.id}
                entry={entry}
                listId={listId}
                onChanged={refresh}
              />
            ))}
          <div className="button-row">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous observations
            </button>
            <button
              disabled={
                !observations.data || offset + 20 >= observations.data.total
              }
              onClick={() => setOffset(offset + 20)}
            >
              Next observations
            </button>
          </div>
          <p>
            Stop following keeps current books as local entries and removes this
            subscription's observation and exclusion history.
          </p>
          <button disabled={detach.isPending} onClick={() => detach.mutate()}>
            Stop following and keep books
          </button>
        </details>
      )}
      {hardcover && data && <ListWriteback key={data.id} listId={listId} />}
    </section>
  );
}

function SubscriptionSettings({
  data,
  pending,
  provider,
  onProvider,
  onSave,
}: {
  data: Subscription | null | undefined;
  pending: boolean;
  provider: "goodreads" | "hardcover";
  onProvider: (provider: "goodreads" | "hardcover") => void;
  onSave: (form: HTMLFormElement) => void;
}) {
  return (
    <details open={!data}>
      <summary>Shelf connection settings</summary>
      <form
        className="editor"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(event.currentTarget);
        }}
      >
        <label>
          List provider
          <select
            aria-label="List provider"
            value={provider}
            disabled={!!data}
            onChange={(e) =>
              onProvider(e.target.value as "goodreads" | "hardcover")
            }
          >
            <option value="goodreads">Goodreads RSS</option>
            <option value="hardcover">Hardcover</option>
          </select>
          <input type="hidden" name="provider" value={provider} />
        </label>
        {provider === "hardcover" ? (
          <HardcoverChoice data={data} />
        ) : (
          <label>
            Goodreads RSS URL
            <input
              name="url"
              type="password"
              autoComplete="off"
              required={!data}
              placeholder={
                data
                  ? "Saved securely; leave blank to keep"
                  : "https://www.goodreads.com/review/list_rss/…"
              }
              maxLength={2000}
            />
          </label>
        )}
        <label>
          Check every (minutes)
          <input
            name="interval"
            type="number"
            min={30}
            max={1440}
            defaultValue={data?.interval_minutes || 30}
            required
          />
        </label>
        <label className="check-label">
          <input
            name="enabled"
            type="checkbox"
            defaultChecked={data?.enabled ?? true}
          />
          Observe shelf additions
        </label>
        <p className="muted">
          Pausing keeps this list and its exclusions. Start another local list
          to follow a different source list.
        </p>
        <button className="primary" disabled={pending}>
          {data ? "Save shelf settings" : "Follow shelf"}
        </button>
      </form>
    </details>
  );
}

function ObservedEntry({
  entry,
  listId,
  onChanged,
}: {
  entry: Observation;
  listId: string;
  onChanged: () => void;
}) {
  const [matching, setMatching] = useState(false);
  const match = useMutation({
    mutationFn: async (q: string) =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q, limit: 20 } },
        }),
      ),
  });
  const update = useMutation({
    mutationFn: async (body: { excluded?: boolean; work_id?: string }) =>
      result(
        await api.PATCH(
          "/api/lists/{list_id}/subscription/observations/{observation_id}",
          {
            params: { path: { list_id: listId, observation_id: entry.id } },
            body,
          },
        ),
      ),
    onSuccess: () => {
      setMatching(false);
      onChanged();
    },
  });
  return (
    <article
      className="panel editor"
      aria-label={`Shelf entry: ${entry.title}`}
    >
      <h3>{entry.title}</h3>
      <p>{entry.authors.join(", ") || "Author not supplied"}</p>
      {entry.work_id ? (
        <Link to={`/books/${entry.work_id}`}>
          Catalog book: {entry.catalog_title}
        </Link>
      ) : (
        <p>The linked catalog book is no longer accessible.</p>
      )}
      {!entry.present && (
        <p className="muted">
          No longer present in the verified source list. Any separately added
          local entry is preserved.
        </p>
      )}
      {entry.identity_changed && (
        <p className="notice">
          The source identity changed. Review the linked catalog book; its
          metadata was preserved.
        </p>
      )}
      <Notice error={match.error || update.error} />
      <div className="button-row">
        <button
          disabled={update.isPending || !entry.present}
          onClick={() => update.mutate({ excluded: !entry.excluded })}
        >
          {entry.excluded ? "Restore to this list" : "Exclude from this shelf"}
        </button>
        <button onClick={() => setMatching(!matching)}>
          Match a catalog book
        </button>
      </div>
      {matching && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            match.mutate(String(new FormData(event.currentTarget).get("q")));
          }}
        >
          <label>
            Find the matching catalog book
            <input
              name="q"
              defaultValue={entry.title}
              required
              maxLength={300}
            />
          </label>
          <button disabled={match.isPending}>Find catalog matches</button>
          {match.data?.items.map((work) => (
            <button
              type="button"
              key={work.id}
              disabled={update.isPending}
              onClick={() => update.mutate({ work_id: work.id })}
            >
              Use {work.title} · {work.authors.join(", ")}
            </button>
          ))}
        </form>
      )}
    </article>
  );
}

function HardcoverChoice({ data }: { data: Subscription | null | undefined }) {
  const [mode, setMode] = useState<"owned" | "followed" | "public">("owned");
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState(
    String(data?.hardcover_list_id || ""),
  );
  const options = useQuery({
    queryKey: ["hardcover-lists", mode, cursor],
    enabled: !data,
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/hardcover-lists", {
          params: { query: { mode, cursor } },
        }),
      ),
  });
  return (
    <>
      <p className="muted">
        Uses your account in <Link to="/metadata">Metadata settings</Link>. Your
        token needs access to lists and book metadata.
      </p>
      {!data ? (
        <>
          <label>
            Browse Hardcover lists
            <select
              aria-label="Browse Hardcover lists"
              value={mode}
              onChange={(e) => {
                setMode(e.target.value as typeof mode);
                setCursor(0);
              }}
            >
              <option value="owned">My lists</option>
              <option value="followed">Lists I follow</option>
              <option value="public">Public lists</option>
            </select>
          </label>
          <Notice error={options.error} />
          <label>
            Choose a Hardcover list
            <select
              aria-label="Choose a Hardcover list"
              value={
                options.data?.items.some(
                  (item) => item.external_id === selected,
                )
                  ? selected
                  : ""
              }
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">
                {options.isFetching
                  ? "Loading lists…"
                  : "Choose a list or enter its ID below"}
              </option>
              {options.data?.items.map((item) => (
                <option key={item.external_id} value={item.external_id}>
                  {item.name} · {item.count} books ·{" "}
                  {item.public ? "Public" : "Restricted"}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              type="button"
              disabled={!cursor || options.isFetching}
              onClick={() => setCursor(0)}
            >
              First list page
            </button>
            <button
              type="button"
              disabled={!options.data?.next_cursor || options.isFetching}
              onClick={() => setCursor(options.data!.next_cursor!)}
            >
              More Hardcover lists
            </button>
          </div>
        </>
      ) : null}
      <label>
        Hardcover list ID
        <input
          name="hardcover_id"
          type="number"
          min={1}
          max={2147483647}
          required
          value={selected}
          readOnly={!!data}
          onChange={(e) => setSelected(e.target.value)}
        />
      </label>
      <p className="muted">
        Local following does not follow or modify the list on Hardcover. No
        library files are removed.
      </p>
    </>
  );
}
