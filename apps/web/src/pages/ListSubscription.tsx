import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import ListWriteback from "./ListWriteback";
import { randomUUID } from "../randomUUID";

type Subscription = components["schemas"]["SubscriptionView"];

export default function ListSubscription({
  listId,
  onMembershipChange,
}: {
  listId: string;
  onMembershipChange?: () => void;
}) {
  const cache = useQueryClient();
  const [choice, setChoice] = useState<"goodreads" | "hardcover">("goodreads");
  const key = useRef(randomUUID());
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
      key.current = randomUUID();
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
      <h2>{data ? "List updates" : "Connect a reading list"}</h2>
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
        <button disabled={detach.isPending} onClick={() => detach.mutate()}>
          Stop following and keep books
        </button>
      )}
      {hardcover && data && (
        <ListWriteback
          key={data.id}
          listId={listId}
          onMembershipChange={onMembershipChange}
        />
      )}
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
                  ? "••••••••"
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

function HardcoverChoice({ data }: { data: Subscription | null | undefined }) {
  const [mode, setMode] = useState<"owned" | "followed" | "public">("owned");
  const [selected, setSelected] = useState(
    String(data?.hardcover_list_id || ""),
  );
  const options = usePagedQuery({
    queryKey: ["hardcover-lists", mode],
    enabled: !data,
    queryFn: async (cursor, signal) =>
      result(
        await api.GET("/api/metadata/hardcover-lists", {
          params: { query: { mode, cursor } },
          signal,
        }),
      ),
    initial: 0,
    next: (last) => last.next_cursor ?? undefined,
  });
  return (
    <>
      <p className="muted">
        Uses your account in{" "}
        <Link to="/settings#catalog">Metadata settings</Link>. Your token needs
        access to lists and book metadata.
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
          <InfiniteScroll query={options} />
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
