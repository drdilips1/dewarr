import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";
import type { components } from "../api/schema";
import { randomUUID } from "../randomUUID";

type Difference = components["schemas"]["ListDifferenceView"];
type Filter =
  "differences" | "all" | "local_only" | "remote_only" | "unmatched";
const labels: Record<string, string> = {
  same: "On both lists",
  local_only: "Only on this list",
  remote_only: "Only on Hardcover",
  unmatched: "Needs matching",
};

export default function ListDifferences({
  listId,
  comparisonId,
  generation,
  enabled,
  onReady,
  onApplied,
}: {
  listId: string;
  comparisonId: string;
  generation: number;
  enabled: boolean;
  onReady: (ready: boolean) => void;
  onApplied: (message: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<Filter>("differences");
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Map<string, Difference>());
  const keys = useRef(new Map<string, string>());
  const path = { list_id: listId, comparison_id: comparisonId };
  const query = useQuery({
    queryKey: [
      "list-differences",
      listId,
      comparisonId,
      offset,
      filter,
      search,
    ],
    queryFn: async () =>
      result(
        await api.GET(
          "/api/lists/{list_id}/writeback/differences/{comparison_id}",
          {
            params: {
              path,
              query: { offset, limit: 10, state: filter, q: search },
            },
          },
        ),
      ),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchInterval: (state) =>
      state.state.error
        ? false
        : ["queued", "running"].includes(state.state.data?.status ?? "queued")
          ? 1500
          : 10000,
  });
  const ready = query.data?.status === "completed" && !query.isError;
  useEffect(() => onReady(ready), [onReady, ready]);
  const apply = useMutation({
    mutationFn: async (action: "apply_local" | "keep_remote") => {
      const rowIds = [...selected.keys()].sort();
      const command = JSON.stringify([
        comparisonId,
        rowIds,
        action,
        generation,
      ]);
      if (!keys.current.has(command)) keys.current.set(command, randomUUID());
      return result(
        await api.POST(
          "/api/lists/{list_id}/writeback/differences/{comparison_id}/resolve",
          {
            params: {
              path,
              header: { "idempotency-key": keys.current.get(command)! },
            },
            body: {
              row_ids: rowIds,
              action,
              expected_policy_generation: generation,
            },
          },
        ),
      );
    },
    onSuccess: (receipt) => onApplied(receipt.message),
  });
  const toggle = (row: Difference) =>
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(row.id)) next.delete(row.id);
      else if (next.size < 100) next.set(row.id, row);
      return next;
    });
  const choice = [...selected.values()];
  const disabled = !ready || apply.isPending;
  return (
    <section
      className="list-differences"
      aria-label="Existing list differences"
    >
      <h3>Compare existing books</h3>
      <p>
        Review this list against Hardcover before sending changes. Select up to
        100 differences across pages. Nothing is selected automatically.
      </p>
      <Notice error={query.error || apply.error} />
      {query.isPending && <p role="status">Loading comparison…</p>}
      {!query.isError && query.data && (
        <>
          <p role="status">{query.data.message}</p>
          {ready && (
            <>
              <p className="muted">
                {query.data.counts.local_only ?? 0} only here ·{" "}
                {query.data.counts.remote_only ?? 0} only on Hardcover ·{" "}
                {query.data.counts.same ?? 0} on both ·{" "}
                {query.data.counts.unmatched ?? 0} need matching
              </p>
              <form
                className="button-row"
                onSubmit={(event) => {
                  event.preventDefault();
                  setSearch(draft);
                  setOffset(0);
                }}
              >
                <label>
                  Find a difference
                  <input
                    value={draft}
                    maxLength={200}
                    onChange={(event) => setDraft(event.target.value)}
                  />
                </label>
                <button disabled={apply.isPending}>Search differences</button>
                <label>
                  Show memberships
                  <select
                    value={filter}
                    onChange={(event) => {
                      setFilter(event.target.value as Filter);
                      setOffset(0);
                    }}
                  >
                    <option value="differences">
                      Differences and unmatched
                    </option>
                    <option value="all">All compared books</option>
                    <option value="local_only">Only on this list</option>
                    <option value="remote_only">Only on Hardcover</option>
                    <option value="unmatched">Needs matching</option>
                  </select>
                </label>
              </form>
              {query.data.items.length === 0 && (
                <p>No books match this view.</p>
              )}
              {query.data.items.map((row) => (
                <article className="writeback-change" key={row.id}>
                  <div className="difference-choice">
                    {(row.can_apply_local || row.can_keep_remote) && (
                      <input
                        type="checkbox"
                        aria-label={`Select difference for ${row.title}`}
                        checked={selected.has(row.id)}
                        disabled={
                          apply.isPending ||
                          (!selected.has(row.id) && selected.size >= 100)
                        }
                        onChange={() => toggle(row)}
                      />
                    )}
                    <strong>
                      {row.work_id ? (
                        <Link to={`/books/${row.work_id}`}>{row.title}</Link>
                      ) : (
                        row.title
                      )}
                    </strong>
                  </div>
                  <p>{labels[row.state] ?? row.state}</p>
                  {row.reason && <p className="muted">{row.reason}</p>}
                </article>
              ))}
              <div className="button-row">
                <button
                  disabled={offset === 0 || apply.isPending}
                  onClick={() => setOffset(Math.max(0, offset - 10))}
                >
                  Previous differences
                </button>
                <span>
                  {query.data.total
                    ? `${offset + 1}–${Math.min(offset + 10, query.data.total)} of ${query.data.total}`
                    : "0 books"}
                </span>
                <button
                  disabled={offset + 10 >= query.data.total || apply.isPending}
                  onClick={() => setOffset(offset + 10)}
                >
                  Next differences
                </button>
              </div>
              <p role="status">{selected.size} selected across pages</p>
              <p className="muted">
                Apply local state sends selected additions or removals to
                Hardcover. Keep Hardcover state changes this local list. Library
                files and reading progress stay unchanged. Refresh the
                comparison after applying a selection.
              </p>
              {!enabled && (
                <p>
                  Enable future changes above before sending selected
                  differences to Hardcover.
                </p>
              )}
              <div className="button-row">
                <button
                  disabled={
                    disabled ||
                    !enabled ||
                    choice.length === 0 ||
                    choice.some((row) => !row.can_apply_local)
                  }
                  onClick={() => apply.mutate("apply_local")}
                >
                  Apply local state to selected
                </button>
                <button
                  disabled={
                    disabled ||
                    choice.length === 0 ||
                    choice.some((row) => !row.can_keep_remote)
                  }
                  onClick={() => apply.mutate("keep_remote")}
                >
                  Keep Hardcover state for selected
                </button>
                <button
                  disabled={apply.isPending || selected.size === 0}
                  onClick={() => setSelected(new Map())}
                >
                  Clear difference selection
                </button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
