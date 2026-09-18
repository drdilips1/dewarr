import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import RequestPreferences, { type Choice } from "./RequestPreferences";
import { EffectiveScope } from "./ScopeFields";
import { EffectivePreferences } from "./PreferenceFields";

type Spec = components["schemas"]["RequestOptions"];
type Preview = components["schemas"]["SeriesRequestView"];
const states: Record<string, string> = {
  satisfied: "Available",
  wanted: "Missing",
  pending: "Already requested",
  "awaiting-inventory": "Check inventory",
  paused: "Needs attention",
  cancelled: "Cancelled",
};

export default function SeriesRequests({
  externalId,
  generation,
  selected,
}: {
  externalId: string;
  generation: number;
  selected: string[];
}) {
  const cache = useQueryClient();
  const [id, setId] = useState<string | null>(null);
  const [scope, setScope] = useState<"selected" | "complete_series">(
    "selected",
  );
  const [confirmed, setConfirmed] = useState(false);
  const [spec, setSpec] = useState<Spec>({});
  const [preferences, setPreferences] = useState<Choice>({});
  const [offset, setOffset] = useState(0);
  const key = useRef(crypto.randomUUID());
  const panel = useRef<HTMLElement>(null);
  const path = { external_id: externalId };
  const history = useQuery({
    queryKey: ["series-requests", externalId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/series/hardcover/{external_id}/requests", {
          params: { path, query: { offset, limit: 10 } },
        }),
      ),
  });
  const saved = useQuery({
    queryKey: ["series-request", externalId, id],
    enabled: Boolean(id),
    queryFn: async () =>
      result(
        await api.GET(
          "/api/catalog/series/hardcover/{external_id}/requests/{operation_id}",
          { params: { path: { ...path, operation_id: id! } } },
        ),
      ),
    refetchInterval: (q) =>
      ["queued", "running"].includes(q.state.data?.status || "")
        ? 1000
        : q.state.data?.status === "completed" &&
            q.state.data.records.some((book) =>
              book.targets.some(
                (target) => !["satisfied", "cancelled"].includes(target.state),
              ),
            )
          ? 10000
          : false,
  });
  const updated = (data: Preview) => {
    cache.setQueryData(["series-request", externalId, data.id], data);
    setId(data.id);
    for (const name of ["series-requests", "requests", "activity"])
      void cache.invalidateQueries({ queryKey: [name] });
  };
  useEffect(() => {
    if (id) panel.current?.focus();
  }, [id]);
  useEffect(() => {
    if (
      saved.data?.status === "completed" ||
      saved.data?.status === "cancelled"
    ) {
      for (const name of ["series-requests", "requests", "activity"])
        void cache.invalidateQueries({ queryKey: [name] });
    }
  }, [saved.data?.status, cache]);
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/catalog/series/hardcover/{external_id}/requests/preview",
          {
            params: { path, header: { "idempotency-key": key.current } },
            body: {
              work_ids: selected,
              specification: spec,
              release_preferences: preferences,
              scope,
              confirm_main_membership: confirmed,
              expected_generation: generation,
            },
          },
        ),
      ),
    onSuccess: updated,
  });
  const submit = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/catalog/series/hardcover/{external_id}/requests/{operation_id}/submit",
          { params: { path: { ...path, operation_id: id! } } },
        ),
      ),
    onSuccess: updated,
  });
  const cancel = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/catalog/series/hardcover/{external_id}/requests/{operation_id}/cancel",
          { params: { path: { ...path, operation_id: id! } } },
        ),
      ),
    onSuccess: updated,
  });
  // A changed draft gets a new key; retries of the same draft retain their key.
  const draft = JSON.stringify({
    selected,
    spec,
    preferences,
    scope,
    confirmed,
    generation,
  });
  const lastDraft = useRef(draft);
  useEffect(() => {
    if (lastDraft.current !== draft) {
      key.current = crypto.randomUUID();
      lastDraft.current = draft;
      preview.reset();
    }
  }, [draft]);
  const value = saved.data;
  const busy =
    preview.isPending ||
    submit.isPending ||
    cancel.isPending ||
    ["queued", "running"].includes(value?.status || "");
  return (
    <section
      className="panel editor"
      aria-label="Series requests"
      tabIndex={-1}
      ref={panel}
    >
      <h2>Request books from this series</h2>
      <p>
        Choose books above, review what is missing, then save your requests.
        Future additions to the series are not included. Release selection
        remains a separate step.
      </p>
      <Notice
        error={
          preview.error ||
          saved.error ||
          submit.error ||
          cancel.error ||
          history.error
        }
      />
      {!id ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            preview.mutate();
          }}
        >
          <fieldset className="editor" disabled={preview.isPending}>
            <legend>{selected.length} books selected · maximum 100</legend>
            <label>
              Series request scope
              <select
                value={scope}
                onChange={(e) => {
                  setScope(e.target.value as typeof scope);
                  setConfirmed(false);
                }}
              >
                <option value="selected">Selected books</option>
                <option value="complete_series">
                  Complete reviewed main-book set
                </option>
              </select>
            </label>
            {scope === "complete_series" && (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I reviewed the selection and it contains the main books I want
                to complete.
              </label>
            )}
            <label>
              Series requested media
              <select
                value={spec.mode || "inherit"}
                onChange={(e) =>
                  setSpec({
                    ...spec,
                    mode:
                      e.target.value === "inherit"
                        ? undefined
                        : (e.target.value as Spec["mode"]),
                    preferred_medium: undefined,
                  })
                }
              >
                <option value="inherit">Use my defaults</option>
                <option value="ebook">Ebook</option>
                <option value="audio">Audiobook</option>
                <option value="both">Both</option>
                <option value="either">Either medium</option>
              </select>
            </label>
            {spec.mode === "either" && (
              <label>
                Series first medium
                <select
                  value={spec.preferred_medium || "inherit"}
                  onChange={(e) =>
                    setSpec({
                      ...spec,
                      preferred_medium:
                        e.target.value === "inherit"
                          ? undefined
                          : (e.target.value as "ebook" | "audio"),
                    })
                  }
                >
                  <option value="inherit">Use my defaults</option>
                  <option value="audio">Audiobook</option>
                  <option value="ebook">Ebook</option>
                </select>
              </label>
            )}
            <RequestPreferences value={preferences} onChange={setPreferences} />
            <button
              disabled={
                !selected.length ||
                selected.length > 100 ||
                (scope === "complete_series" && !confirmed)
              }
            >
              Preview series requests
            </button>
          </fieldset>
        </form>
      ) : value ? (
        <>
          <p role="status">{value.message}</p>
          <p>
            {value.records.length} selected books · {value.counts.satisfied}{" "}
            available media targets · {value.counts.wanted} missing ·{" "}
            {value.counts.pending} already requested
            {value.counts.cancelled > 0 &&
              ` · ${value.counts.cancelled} cancelled`}
          </p>
          {value.main_membership === "user-confirmed" && (
            <p>
              These are your reviewed main books, saved from catalog revision{" "}
              {value.catalog_generation}.
            </p>
          )}
          <EffectiveScope
            specification={value.specification}
            origins={value.release_policy.scope_origins}
          />
          <EffectivePreferences
            preferences={value.release_policy.preferences}
            origins={value.release_policy.origins || {}}
          />
          <div className="edition-grid">
            {value.records.map((book, index) => (
              <article className="panel" key={`${book.work_id}:${index}`}>
                <h3>
                  <Link to={`/books/${book.work_id}`}>
                    {book.position != null && `${book.position} · `}
                    {book.title}
                  </Link>
                </h3>
                {book.issue && <p>{book.issue}</p>}
                {book.warnings.map((warning) => (
                  <p className="muted" key={warning}>
                    {warning}
                  </p>
                ))}
                {book.targets.map((target) => (
                  <p key={target.slot}>
                    {target.slot === "audio"
                      ? "Audiobook"
                      : target.slot === "ebook"
                        ? "Ebook"
                        : "Either medium"}
                    : {states[target.state] || target.state}
                  </p>
                ))}
                {value.receipt?.find(
                  (receipt) => receipt.work_id === book.work_id,
                ) && (
                  <Link to={`/books/${book.work_id}`}>
                    Open book and source options
                  </Link>
                )}
              </article>
            ))}
          </div>
          {value.omitted.length > 0 && (
            <details>
              <summary>
                {value.omitted.length} books outside this request
              </summary>
              {value.omitted.map((book) => (
                <p key={book.work_id}>
                  {book.title} · {book.warnings.join(" · ") || book.reason}
                </p>
              ))}
            </details>
          )}
          <div className="button-row">
            {["preview", "failed"].includes(value.status) && (
              <button disabled={busy} onClick={() => submit.mutate()}>
                {value.accepted_at
                  ? "Retry saved series request"
                  : "Save series requests"}
              </button>
            )}
            {value.status !== "cancelled" && (
              <button
                disabled={submit.isPending || cancel.isPending}
                onClick={() => cancel.mutate()}
              >
                Cancel this series request
              </button>
            )}
            <button
              disabled={busy}
              onClick={() => {
                setId(null);
                key.current = crypto.randomUUID();
                preview.reset();
                submit.reset();
                cancel.reset();
                panel.current?.focus();
              }}
            >
              New selection
            </button>
          </div>
          <p className="muted">
            Cancellation removes only this series request’s reasons. Other
            requests, existing files and shared downloads remain intact.
          </p>
        </>
      ) : (
        <p role="status">Loading saved series request…</p>
      )}
      {!!history.data?.total && (
        <details>
          <summary>Series request history ({history.data.total})</summary>
          {history.data.items.map((item) => (
            <div className="button-row" key={item.id}>
              <button disabled={busy} onClick={() => setId(item.id)}>
                Open {item.count}-book request ·{" "}
                {new Date(item.created_at).toLocaleString()}
              </button>
              <span>{item.status}</span>
            </div>
          ))}
          <nav className="button-row" aria-label="Series request history pages">
            <button
              disabled={!offset || busy}
              onClick={() => setOffset(Math.max(0, offset - 10))}
            >
              Previous history
            </button>
            <button
              disabled={offset + 10 >= history.data.total || busy}
              onClick={() => setOffset(offset + 10)}
            >
              Next history
            </button>
          </nav>
        </details>
      )}
    </section>
  );
}
