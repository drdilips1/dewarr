import RequestPreferences, { type Choice } from "./RequestPreferences";
import { EffectivePreferences } from "./PreferenceFields";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import DownloadConstraints from "./DownloadConstraints";

type Spec = components["schemas"]["RequestSpec"];
type Work = components["schemas"]["WorkView"];
const states: Record<string, string> = {
  satisfied: "Available",
  wanted: "Missing",
  pending: "Already requested",
  "awaiting-inventory": "Check inventory",
  paused: "Needs a decision",
  unresolved: "Needs review",
};
const media: Record<string, string> = {
  ebook: "Ebook",
  audio: "Audiobook",
  both: "Both",
  either: "Either medium",
};

export default function ListRequests({
  listId,
  works,
}: {
  listId: string;
  works: Work[];
}) {
  const policy = useQuery({
    queryKey: ["list-policy", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/acquisition", {
          params: { path: { list_id: listId } },
        }),
      ),
  });
  if (policy.isPending) return <Loading />;
  if (policy.isError) return <Notice error={policy.error} />;
  return (
    <ListRequestEditor
      key={`${listId}:${policy.data?.revision || 0}`}
      listId={listId}
      works={works}
      defaults={
        policy.data
          ? {
              ...policy.data.configuration.specification,
              download_constraints:
                policy.data.configuration.request_constraints,
            }
          : undefined
      }
      profile={policy.data?.configuration.profile}
    />
  );
}

function ListRequestEditor({
  listId,
  works,
  defaults,
  profile,
}: {
  listId: string;
  works: Work[];
  defaults?: Spec;
  profile?: components["schemas"]["ProfileSnapshot"];
}) {
  const client = useQueryClient();
  const path = { list_id: listId };
  const [id, setId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [spec, setSpec] = useState<Spec>(
    defaults ?? {
      mode: "either",
      preferred_medium: "audio",
      standalone: false,
    },
  );
  const [preferences, setPreferences] = useState<Choice>({});
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const key = useRef(crypto.randomUUID());
  const completed = useRef<string | null>(null);
  const history = useQuery({
    queryKey: ["list-request-history", listId, historyOffset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/requests", {
          params: { path, query: { offset: historyOffset, limit: 10 } },
        }),
      ),
  });
  const libraries = useQuery({
    queryKey: ["libraries"],
    queryFn: async () => result(await api.GET("/api/library/libraries")),
  });
  const saved = useQuery({
    queryKey: ["list-request-preview", listId, id],
    enabled: Boolean(id),
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/requests/{operation_id}", {
          params: { path: { ...path, operation_id: id! } },
        }),
      ),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status || "")
        ? 1000
        : false,
  });
  const refresh = () => {
    for (const name of [
      "list-request-history",
      "requests",
      "request-preview",
      "activity",
    ]) {
      void client.invalidateQueries({ queryKey: [name] });
    }
  };
  useEffect(() => {
    if (
      saved.data?.status === "completed" &&
      completed.current !== saved.data.id
    ) {
      completed.current = saved.data.id;
      for (const name of [
        "list-request-history",
        "requests",
        "request-preview",
        "activity",
      ]) {
        void client.invalidateQueries({ queryKey: [name] });
      }
    }
  }, [saved.data, client]);
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/requests/preview", {
          params: { path, header: { "idempotency-key": key.current } },
          body: {
            work_ids: selected,
            specification: spec,
            release_preferences: preferences,
          },
        }),
      ),
    onSuccess: (data) => {
      client.setQueryData(["list-request-preview", listId, data.id], data);
      setId(data.id);
      refresh();
    },
  });
  const submit = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/requests/{operation_id}/submit", {
          params: { path: { ...path, operation_id: id! } },
        }),
      ),
    onSuccess: (data) => {
      client.setQueryData(["list-request-preview", listId, data.id], data);
      refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/requests/{operation_id}/cancel", {
          params: { path: { ...path, operation_id: id! } },
        }),
      ),
    onSuccess: (data) => {
      client.setQueryData(["list-request-preview", listId, data.id], data);
      refresh();
    },
  });
  const changed = () => {
    key.current = crypto.randomUUID();
    preview.reset();
  };
  const filtered = works.filter((w) =>
    `${w.title} ${w.authors.join(" ")}`
      .toLocaleLowerCase()
      .includes(filter.toLocaleLowerCase()),
  );
  const visible = filtered.slice(page * 25, (page + 1) * 25);
  const chosen = new Set(selected);
  const combined = [...new Set([...selected, ...visible.map((w) => w.id)])];
  const value = saved.data;
  return (
    <section className="panel editor" aria-label="List wanted media">
      <h2>Request books from this list</h2>
      <p className="muted">
        Choose up to 100 books, check what you already have, then save the media
        you want. Release selection and download remain separate steps.
      </p>
      {defaults && (
        <p className="muted">
          Media, destinations and download limits start from this list’s saved
          policy. You can change them for this request.
        </p>
      )}
      <Notice
        error={
          preview.error ||
          saved.error ||
          submit.error ||
          cancel.error ||
          history.error ||
          libraries.error
        }
      />
      {!id ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            preview.mutate();
          }}
        >
          <fieldset disabled={preview.isPending} className="editor">
            <legend>Select books and media</legend>
            <label>
              Find books in this list
              <input
                value={filter}
                onChange={(event) => {
                  setFilter(event.target.value);
                  setPage(0);
                }}
              />
            </label>
            <p>
              {selected.length} selected · {filtered.length} matching books
            </p>
            <div className="inline-form">
              <button
                type="button"
                disabled={!visible.length || combined.length > 100}
                onClick={() => {
                  setSelected(combined);
                  changed();
                }}
              >
                Select this page
              </button>
              <button
                type="button"
                disabled={!selected.length}
                onClick={() => {
                  setSelected([]);
                  changed();
                }}
              >
                Clear selection
              </button>
            </div>
            {visible.map((work) => (
              <label className="checkbox" key={work.id}>
                <input
                  type="checkbox"
                  checked={chosen.has(work.id)}
                  disabled={!chosen.has(work.id) && selected.length >= 100}
                  onChange={(event) => {
                    setSelected(
                      event.target.checked
                        ? [...selected, work.id]
                        : selected.filter((v) => v !== work.id),
                    );
                    changed();
                  }}
                />
                {work.title} {work.availability.owned ? "· In library" : ""}
              </label>
            ))}
            <div className="inline-form">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous books
              </button>
              <span>
                Page {page + 1} of{" "}
                {Math.max(1, Math.ceil(filtered.length / 25))}
              </span>
              <button
                type="button"
                disabled={(page + 1) * 25 >= filtered.length}
                onClick={() => setPage(page + 1)}
              >
                Next books
              </button>
            </div>
            <label>
              Media to request
              <select
                value={spec.mode}
                onChange={(event) => {
                  const mode = event.target.value as Spec["mode"];
                  setSpec({
                    ...spec,
                    mode,
                    preferred_medium: mode === "either" ? "audio" : null,
                    ...(mode === "ebook"
                      ? { audio_library_id: null, abridged: null }
                      : {}),
                    ...(mode === "audio" ? { ebook_library_id: null } : {}),
                  });
                  changed();
                }}
              >
                <option value="either">Either ebook or audiobook</option>
                <option value="both">Both ebook and audiobook</option>
                <option value="ebook">Ebook</option>
                <option value="audio">Audiobook</option>
              </select>
            </label>
            {spec.mode === "either" && (
              <label>
                When neither is available
                <select
                  value={spec.preferred_medium || "audio"}
                  onChange={(event) => {
                    setSpec({
                      ...spec,
                      preferred_medium: event.target.value as "ebook" | "audio",
                    });
                    changed();
                  }}
                >
                  <option value="audio">Prefer audiobook</option>
                  <option value="ebook">Prefer ebook</option>
                </select>
              </label>
            )}
            <details>
              <summary>Language and destinations</summary>
              <label>
                Required language (optional)
                <input
                  value={spec.language || ""}
                  maxLength={20}
                  placeholder="e.g. en"
                  pattern="[a-zA-Z]{2,3}([-_][a-zA-Z0-9]{2,8})*"
                  onChange={(event) => {
                    setSpec({ ...spec, language: event.target.value || null });
                    changed();
                  }}
                />
              </label>
              {(["ebook", "audio"] as const)
                .filter(
                  (m) =>
                    spec.mode === m ||
                    spec.mode === "both" ||
                    spec.mode === "either",
                )
                .map((m) => (
                  <label key={m}>
                    {media[m]} destination
                    <select
                      value={spec[`${m}_library_id`] || ""}
                      onChange={(event) => {
                        setSpec({
                          ...spec,
                          [`${m}_library_id`]: event.target.value || null,
                        });
                        changed();
                      }}
                    >
                      <option value="">Choose during release selection</option>
                      {libraries.data
                        ?.filter((l) => l.accessible)
                        .map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.name}
                          </option>
                        ))}
                    </select>
                  </label>
                ))}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={spec.standalone || false}
                  onChange={(event) => {
                    setSpec({ ...spec, standalone: event.target.checked });
                    changed();
                  }}
                />
                Require standalone copies
              </label>
              {spec.mode !== "ebook" && (
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={spec.abridged === false}
                    onChange={(event) => {
                      setSpec({
                        ...spec,
                        abridged: event.target.checked ? false : null,
                      });
                      changed();
                    }}
                  />
                  Require unabridged audiobooks
                </label>
              )}
            </details>
            <RequestPreferences
              value={preferences}
              inherited={profile}
              onChange={(value) => {
                setPreferences(value);
                key.current = crypto.randomUUID();
              }}
            />
            <button
              className="primary"
              disabled={!selected.length || preview.isPending}
            >
              Preview wanted media
            </button>
          </fieldset>
        </form>
      ) : saved.isPending ? (
        <Loading />
      ) : value ? (
        <>
          <h3>
            {media[value.specification.mode]} · {value.records.length} selected{" "}
            {value.records.length === 1 ? "book" : "books"}
          </h3>
          <p role="status">{value.message}</p>
          <p className="muted">
            Current media targets:{" "}
            {Object.entries(value.counts)
              .filter(([, count]) => count)
              .map(
                ([state, count]) =>
                  `${count} ${states[state]?.toLocaleLowerCase() || state}`,
              )
              .join(" · ")}
            . Inventory is checked again when saving.
          </p>
          {value.release_policy && (
            <EffectivePreferences
              preferences={value.release_policy.preferences}
              origins={value.release_policy.origins || {}}
            />
          )}
          {value.specification.language && (
            <p>Required language: {value.specification.language}</p>
          )}
          <DownloadConstraints
            value={value.specification.download_constraints}
          />
          {value.records.map((record) => (
            <article key={record.work_id} className="source-attribution">
              <div>
                {record.issue ? (
                  <strong>{record.title}</strong>
                ) : (
                  <Link to={`/books/${record.work_id}`}>{record.title}</Link>
                )}
                {record.issue ? (
                  <p>{record.issue}</p>
                ) : (
                  record.targets.map((t) => (
                    <p key={t.slot}>
                      {media[t.slot]}: {states[t.state] || t.state} ·{" "}
                      {t.message}
                    </p>
                  ))
                )}
              </div>
            </article>
          ))}
          <div className="inline-form">
            {["preview", "failed"].includes(value.status) && (
              <button
                className="primary"
                disabled={
                  submit.isPending ||
                  cancel.isPending ||
                  Boolean(value.counts.unresolved)
                }
                onClick={() => submit.mutate()}
              >
                {value.status === "failed"
                  ? "Retry saving wanted media"
                  : "Save wanted media"}
              </button>
            )}
            {!["completed", "cancelled"].includes(value.status) && (
              <button
                disabled={cancel.isPending || submit.isPending}
                onClick={() => cancel.mutate()}
              >
                Cancel this batch
              </button>
            )}
            <button
              disabled={submit.isPending || cancel.isPending}
              onClick={() => {
                setSelected(value.records.map((r) => r.work_id));
                setSpec(value.specification);
                setId(null);
                changed();
                submit.reset();
                cancel.reset();
              }}
            >
              New selection
            </button>
          </div>
          {value.receipt && (
            <p>
              Saved {value.receipt.length} request{" "}
              {value.receipt.length === 1 ? "link" : "links"}. Reopening this
              receipt does not request these books again. Open a book to choose
              a release or manage its request reasons.
            </p>
          )}
        </>
      ) : null}
      {history.data?.items.length ? (
        <details>
          <summary>Saved previews and request receipts</summary>
          {history.data.items.map((item) => (
            <p key={item.id}>
              <button
                type="button"
                onClick={() => {
                  setId(item.id);
                  submit.reset();
                  cancel.reset();
                }}
              >
                {item.count} {item.count === 1 ? "book" : "books"} ·{" "}
                {item.status} · {new Date(item.created_at).toLocaleString()}
              </button>
            </p>
          ))}
          <div className="inline-form">
            <button
              disabled={historyOffset === 0}
              onClick={() => setHistoryOffset(Math.max(0, historyOffset - 10))}
            >
              Previous request batches
            </button>
            <button
              disabled={historyOffset + 10 >= history.data.total}
              onClick={() => setHistoryOffset(historyOffset + 10)}
            >
              Next request batches
            </button>
          </div>
        </details>
      ) : null}
    </section>
  );
}
