import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, Library, Plus } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import InfiniteScroll from "../components/InfiniteScroll";
import { usePagedQuery } from "../hooks/usePagedQuery";

type ListView = components["schemas"]["ListView"];
type Subscription = components["schemas"]["ReadingSubscription"];
type Provider = Subscription["subscription"]["provider"];

function sourceLabel(provider?: Provider) {
  if (provider === "goodreads") return "Goodreads";
  if (provider === "storygraph") return "StoryGraph";
  if (provider === "hardcover") return "Hardcover";
  return "Local";
}

function listMeta(
  list: ListView,
  subscription: Subscription | undefined,
  settled: boolean,
) {
  const parts = [];
  if (settled) parts.push(sourceLabel(subscription?.subscription.provider));
  if (typeof list.count === "number")
    parts.push(`${list.count} ${list.count === 1 ? "book" : "books"}`);
  if (list.shared) parts.push("Shared");
  if (subscription && !subscription.subscription.enabled) parts.push("Paused");
  return parts.join(" · ");
}

function SourceMark({
  provider,
  pending = false,
}: {
  provider?: Provider;
  pending?: boolean;
}) {
  return (
    <span className="list-choice-mark" aria-hidden="true">
      {pending ? null : provider === "goodreads" ? (
        "g"
      ) : provider === "storygraph" ? (
        "s"
      ) : provider === "hardcover" ? (
        <BookOpen size={16} />
      ) : (
        <Library size={16} />
      )}
    </span>
  );
}

export default function ListChoice({
  value,
  onChange,
  label,
  disabled = false,
}: {
  value: string;
  onChange: (id: string) => void;
  label: string;
  disabled?: boolean;
}) {
  const labelId = useId();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<ListView | null>(null);
  const [createdName, setCreatedName] = useState("");
  const cache = useQueryClient();
  const lists = usePagedQuery({
    queryKey: ["lists", "choice", search],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/lists/page", {
          signal,
          params: { query: { editable: true, q: search, offset, limit: 25 } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((total, page) => total + page.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  const subscriptions = useQuery({
    queryKey: ["reading-subscriptions"],
    retry: false,
    queryFn: async () =>
      result(await api.GET("/api/reading-accounts/subscriptions")),
  });
  const linked = new Map(
    (Array.isArray(subscriptions.data) ? subscriptions.data : []).map(
      (entry) => [entry.list_id, entry],
    ),
  );
  const sourcesReady = subscriptions.isFetched;
  const create = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists", {
          body: { name: name.trim(), shared: false },
        }),
      ),
    onSuccess: async (list) => {
      setChosen(list);
      setCreatedName(list.name);
      setCreating(false);
      setName("");
      setSearch("");
      onChange(list.id);
      await cache.invalidateQueries({ queryKey: ["lists"] });
    },
  });
  const items = lists.data?.items ?? [];
  const visible =
    chosen && !search.trim() && !items.some((list) => list.id === chosen.id)
      ? [chosen, ...items]
      : items;
  const choose = (list: ListView) => {
    setChosen(list);
    setCreatedName("");
    onChange(list.id);
  };
  return (
    <div className="list-choice grow">
      <label>
        Find lists by name
        <input
          value={search}
          disabled={disabled}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <Notice error={lists.error} />
      <div>
        <span className="list-choice-label" id={labelId}>
          {label}
        </span>
        {lists.isPending && <Loading />}
        {lists.data?.total === 0 && (
          <p className="muted">
            {search.trim() ? "No lists match that name." : "No lists yet."}
          </p>
        )}
        {chosen &&
          search.trim() &&
          !items.some((list) => list.id === chosen.id) && (
            <p className="muted list-choice-kept">Selected: {chosen.name}</p>
          )}
        <div
          role="radiogroup"
          aria-labelledby={labelId}
          className="list-choice-options"
          onKeyDown={(event) => {
            if (!(event.target instanceof HTMLElement)) return;
            if (event.target.getAttribute("role") !== "radio") return;
            const radios = [
              ...event.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="radio"]',
              ),
            ];
            const index = radios.indexOf(event.target as HTMLButtonElement);
            if (index < 0) return;
            let next = index;
            if (event.key === "ArrowDown" || event.key === "ArrowRight")
              next = Math.min(radios.length - 1, index + 1);
            else if (event.key === "ArrowUp" || event.key === "ArrowLeft")
              next = Math.max(0, index - 1);
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = radios.length - 1;
            else return;
            event.preventDefault();
            radios[next].focus();
            radios[next].click();
          }}
        >
          {visible.map((list) => {
            const subscription = linked.get(list.id);
            const selected = value === list.id;
            return (
              <button
                type="button"
                role="radio"
                id={`list-choice-${list.id}`}
                key={list.id}
                className="list-choice-option"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => choose(list)}
              >
                <SourceMark
                  pending={!sourcesReady}
                  provider={subscription?.subscription.provider}
                />
                <span className="list-choice-copy">
                  <span className="list-choice-name">{list.name}</span>
                  <span className="list-choice-meta">
                    {listMeta(list, subscription, sourcesReady)}
                  </span>
                  {list.description && (
                    <span className="list-choice-description">
                      {list.description}
                    </span>
                  )}
                </span>
                {selected && (
                  <Check
                    className="list-choice-check"
                    size={16}
                    aria-hidden="true"
                  />
                )}
              </button>
            );
          })}
          <InfiniteScroll query={lists} />
        </div>
      </div>
      {creating ? (
        <div className="list-choice-create">
          <label>
            List name
            <input
              autoFocus
              maxLength={200}
              value={name}
              disabled={disabled || create.isPending}
              placeholder="Next on the nightstand"
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                if (name.trim() && !create.isPending) create.mutate();
              }}
            />
          </label>
          <div className="button-row">
            <button
              type="button"
              className="primary"
              disabled={disabled || create.isPending || !name.trim()}
              onClick={() => create.mutate()}
            >
              {create.isPending ? "Creating…" : "Create list"}
            </button>
            <button
              type="button"
              disabled={create.isPending}
              onClick={() => {
                setCreating(false);
                setName("");
                create.reset();
              }}
            >
              Cancel
            </button>
          </div>
          <Notice error={create.error} />
        </div>
      ) : (
        <button
          type="button"
          className="list-choice-option list-choice-new"
          disabled={disabled}
          onClick={() => {
            setCreating(true);
            setCreatedName("");
            create.reset();
          }}
        >
          <Plus size={16} aria-hidden="true" />
          New list
        </button>
      )}
      {createdName && (
        <p className="success" role="status">
          Created {createdName}.
        </p>
      )}
    </div>
  );
}
