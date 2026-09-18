import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import ImportExecution from "../components/ImportExecution";
import GroupingEditor from "../components/GroupingEditor";

type Group = components["schemas"]["InspectedGroup"];
type Selection = components["schemas"]["GroupSelection"];
type Inspection = components["schemas"]["InspectionView"];

export default function ImportReview() {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("inspection");
  const [source, setSource] = useState("");
  const [path, setPath] = useState("");
  const [complete, setComplete] = useState(false);
  const [offset, setOffset] = useState(0);
  const cache = useQueryClient();
  const attempt = useRef<{ payload: string; key: string } | null>(null);
  const roots = useQuery({
    queryKey: ["download-roots"],
    queryFn: async () =>
      result(await api.GET("/api/organization/download-roots")),
  });
  const history = useQuery({
    queryKey: ["inspections", offset],
    queryFn: async () =>
      result(
        await api.GET("/api/organization/inspections", {
          params: { query: { offset } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.some((row) => ["queued", "running"].includes(row.state))
        ? 2000
        : false,
  });
  const selected = useQuery({
    queryKey: ["inspection", selectedId],
    enabled: !!selectedId,
    queryFn: async () =>
      result(
        await api.GET("/api/organization/inspections/{inspection_id}", {
          params: { path: { inspection_id: selectedId! } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data && ["queued", "running"].includes(query.state.data.state)
        ? 1500
        : false,
  });
  const create = useMutation({
    mutationFn: async () => {
      const body = {
        source_key: source || roots.data?.[0] || "",
        relative_path: path,
        completed_download: true as const,
      };
      const payload = JSON.stringify(body);
      if (attempt.current?.payload !== payload)
        attempt.current = { payload, key: crypto.randomUUID() };
      return result(
        await api.POST("/api/organization/inspections", {
          body,
          params: { header: { "idempotency-key": attempt.current.key } },
        }),
      );
    },
    onSuccess: (row) => {
      attempt.current = null;
      setParams({ inspection: row.id });
      cache.setQueryData(["inspection", row.id], row);
      cache.invalidateQueries({ queryKey: ["inspections"] });
    },
  });
  return (
    <>
      <Link to="/organization">← Naming settings</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Library setup</p>
          <h1>Review completed downloads</h1>
          <p className="muted">
            Inspect files, match book groups and save an organization plan.
          </p>
        </div>
      </div>
      <p className="notice">
        Inspection reads source files. Review the plan and choose a verified
        destination before importing. A saved plan does not mark a book as
        owned.
      </p>
      <form
        className="panel editor"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <h2>Inspect a download</h2>
        {!roots.data?.length && !roots.isPending && (
          <p className="notice">
            No download roots are configured. Configure read-only worker mounts
            and BOOK_IMPORT_SOURCES before inspecting files.
          </p>
        )}
        <label>
          Download root
          <select
            value={source || roots.data?.[0] || ""}
            onChange={(event) => setSource(event.target.value)}
            disabled={create.isPending}
          >
            {!roots.data?.length && (
              <option value="">No configured roots</option>
            )}
            {roots.data?.map((key) => (
              <option value={key} key={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <label>
          Download folder
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="Series pack / completed folder"
            maxLength={1024}
            required
            disabled={create.isPending}
          />
        </label>
        <p className="muted">Enter the folder relative to the selected root.</p>
        <label className="check-label">
          <input
            type="checkbox"
            checked={complete}
            onChange={(event) => setComplete(event.target.checked)}
            disabled={create.isPending}
          />
          The download has finished and its files are no longer changing
        </label>
        <Notice error={roots.error || create.error} />
        <button
          className="primary"
          disabled={
            !complete || !path || !roots.data?.length || create.isPending
          }
        >
          {create.isPending ? "Queuing…" : "Inspect files"}
        </button>
      </form>
      <section className="panel editor" aria-label="Inspection history">
        <h2>Recent inspections</h2>
        <Notice error={history.error} />
        {history.data?.map((row) => (
          <div className="import-path" key={row.id}>
            <button onClick={() => setParams({ inspection: row.id })}>
              {row.relative_path} · {row.state}
            </button>
            <span className="muted">{row.message}</span>
          </div>
        ))}
        {history.data?.length === 0 && (
          <p className="muted">No inspections yet.</p>
        )}
        <div className="actions">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((value) => Math.max(0, value - 25))}
          >
            Previous inspections
          </button>
          <button
            disabled={(history.data?.length || 0) < 25}
            onClick={() => setOffset((value) => value + 25)}
          >
            More inspections
          </button>
        </div>
      </section>
      <Notice error={selected.error} />
      {selectedId && selected.isPending && <Loading />}
      {selected.data && (
        <Review key={selected.data.id} inspection={selected.data} />
      )}
    </>
  );
}

function Review({ inspection }: { inspection: Inspection }) {
  const cache = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [groupOffset, setGroupOffset] = useState(0);
  const [fileLimit, setFileLimit] = useState(100);
  const [editingGroups, setEditingGroups] = useState(false);
  const [includeCovers, setIncludeCovers] = useState(true);
  const snapshot = inspection.snapshot;
  const grouping = useQuery({
    queryKey: ["inspection-grouping", inspection.id],
    enabled: !!snapshot && inspection.state === "ready",
    queryFn: async () =>
      result(
        await api.GET(
          "/api/organization/inspections/{inspection_id}/grouping",
          {
            params: { path: { inspection_id: inspection.id } },
          },
        ),
      ),
  });
  const groups = grouping.data?.content.groups || [];
  const planId = params.get("plan");
  const settings = useQuery({
    queryKey: ["naming-review-settings"],
    queryFn: async () => result(await api.GET("/api/organization/settings")),
  });
  const frozen = useQuery({
    queryKey: ["frozen-import-plan", planId],
    enabled: !!planId,
    queryFn: async () =>
      result(
        await api.GET("/api/organization/plans/{plan_id}", {
          params: { path: { plan_id: planId! } },
        }),
      ),
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/organization/inspections/{inspection_id}/plans", {
          params: { path: { inspection_id: inspection.id } },
          body: {
            inspection_revision: snapshot!.revision,
            profile_revision: settings.data!.revision,
            grouping_revision: grouping.data!.revision,
            include_covers: includeCovers,
            selections: Object.values(selections),
          },
        }),
      ),
    onSuccess: (plan) =>
      setParams({ inspection: inspection.id, plan: plan.id }),
  });
  return (
    <section aria-label="Inspected download" className="library-access">
      <h2>{inspection.relative_path}</h2>
      <p role="status">{inspection.message}</p>
      {snapshot && (
        <>
          <p className="muted">
            {snapshot.files.length} files inspected · {groups.length} book
            groups. Embedded metadata is evidence; choose a catalog version to
            confirm each mapping.
          </p>
          <Notice error={grouping.error} />
          {grouping.isPending && <Loading />}
          {grouping.data && !editingGroups && (
            <button
              disabled={save.isPending}
              onClick={() => setEditingGroups(true)}
            >
              Review file groups
            </button>
          )}
          {editingGroups && grouping.data && (
            <GroupingEditor
              key={grouping.data.revision}
              inspection={inspection}
              grouping={grouping.data}
              onCancel={() => setEditingGroups(false)}
              onSave={(value) => {
                cache.setQueryData(
                  ["inspection-grouping", inspection.id],
                  value,
                );
                setSelections({});
                setGroupOffset(0);
                setEditingGroups(false);
                setParams({ inspection: inspection.id });
              }}
            />
          )}
          {grouping.data?.content.excluded.length ? (
            <p className="muted">
              {grouping.data.content.excluded.length} files excluded from this
              plan. Review file groups to see why.
            </p>
          ) : null}
          {!editingGroups &&
            groups.slice(groupOffset, groupOffset + 10).map((group) => (
              <GroupMatch
                key={`${grouping.data?.revision}:${group.key}`}
                group={group}
                selection={selections[group.key]}
                disabled={save.isPending}
                onChange={(selection) =>
                  setSelections((current) => {
                    const next = { ...current };
                    if (selection) next[group.key] = selection;
                    else delete next[group.key];
                    return next;
                  })
                }
              />
            ))}
          <div className="actions">
            <button
              disabled={groupOffset === 0}
              onClick={() => setGroupOffset((value) => Math.max(0, value - 10))}
            >
              Previous groups
            </button>
            <button
              disabled={groupOffset + 10 >= groups.length}
              onClick={() => setGroupOffset((value) => value + 10)}
            >
              More groups
            </button>
          </div>
          <p className="muted">
            {Object.keys(selections).length} groups selected for this plan.
          </p>
          <details>
            <summary>File evidence and items needing review</summary>
            {snapshot.files.slice(0, fileLimit).map((file) => (
              <div className="import-path" key={file.path}>
                <strong>
                  {file.path} · {file.state}
                </strong>
                {file.reason && <span>{file.reason}</span>}
                <span className="muted">SHA-256: {file.sha256}</span>
              </div>
            ))}
            {fileLimit < snapshot.files.length && (
              <button onClick={() => setFileLimit((value) => value + 100)}>
                Show more file evidence
              </button>
            )}
          </details>
          <Notice error={settings.error || save.error} />
          <label className="check-label">
            <input
              type="checkbox"
              checked={includeCovers}
              disabled={save.isPending}
              onChange={(event) => setIncludeCovers(event.target.checked)}
            />
            Include selected catalog covers in new imports
          </label>
          <button
            className="primary"
            disabled={
              save.isPending ||
              !settings.data ||
              !grouping.data ||
              editingGroups ||
              !Object.keys(selections).length
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save import plan"}
          </button>
          {save.isError && (
            <button
              onClick={() => {
                settings.refetch();
                grouping.refetch();
                setSelections({});
              }}
            >
              Refresh review settings
            </button>
          )}
        </>
      )}
      <Notice error={frozen.error} />
      {frozen.data && (
        <article className="panel editor" aria-label="Saved import plan">
          <h3>Import plan saved</h3>
          <Link to={`/organization/destinations?plan=${frozen.data.id}`}>
            Check destination
          </Link>
          <p>
            {frozen.data.document.plan.expected_items} planned item folders ·{" "}
            {frozen.data.document.plan.held_items} need attention
          </p>
          <p className="notice">
            Recorded for review. Source revalidation, destination checks and
            Audiobookshelf compatibility are still required before publication.
          </p>
          <p className="muted">
            {Object.keys(frozen.data.document.cover_sources || {}).length}{" "}
            selected covers. Unavailable artwork is reported without blocking
            the book import.
          </p>
          {frozen.data.document.plan.items.map((item) => (
            <div className="import-path" key={item.group_id}>
              <strong>
                {item.title} · {item.state}
              </strong>
              {item.reason && <span>{item.reason}</span>}
              {(item.files || []).map((file) => (
                <span key={file.source}>
                  {file.source} → {file.destination}
                </span>
              ))}
            </div>
          ))}
          <ImportExecution plan={frozen.data} />
        </article>
      )}
    </section>
  );
}

function GroupMatch({
  group,
  selection,
  disabled,
  onChange,
}: {
  group: Group;
  selection?: Selection;
  disabled: boolean;
  onChange: (selection: Selection | null) => void;
}) {
  const [input, setInput] = useState(group.title || "");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [workId, setWorkId] = useState(selection?.work_id || "");
  const [versionId, setVersionId] = useState(selection?.version_id || "");
  const [versionOffset, setVersionOffset] = useState(0);
  const [full, setFull] = useState(selection?.full_content || false);
  const books = useQuery({
    queryKey: ["import-match-books", q, offset],
    enabled: !!q,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works", {
          params: { query: { q, offset, limit: 20 } },
        }),
      ),
  });
  const versions = useQuery({
    queryKey: ["import-match-versions", workId, versionOffset],
    enabled: !!workId,
    queryFn: async () =>
      result(
        await api.GET("/api/metadata/works/{work_id}", {
          params: {
            path: { work_id: workId },
            query: { offset: versionOffset, limit: 40 },
          },
        }),
      ),
  });
  function update(version: string, complete: boolean) {
    setVersionId(version);
    setFull(complete);
    onChange(
      version
        ? {
            group_key: group.key,
            work_id: workId,
            version_id: version,
            full_content: complete,
          }
        : null,
    );
  }
  return (
    <article
      className="panel editor"
      aria-label={`Match ${group.title || group.files[0]?.path || "book group"}`}
    >
      <h3>
        {group.title || "Unidentified book"} ·{" "}
        {group.medium === "audio" ? "Audiobook" : "Ebook"}
      </h3>
      <p className="muted">
        {group.authors.join(", ") || "Unknown author"}
        {group.narrators.length
          ? ` · ${group.narrators.join(", ")}`
          : ""} · {group.files.length} files
      </p>
      <details>
        <summary>Original file paths</summary>
        {group.files.map((file) => (
          <div className="import-path" key={file.path}>
            {file.path}
          </div>
        ))}
      </details>
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          setQ(input);
          setOffset(0);
        }}
      >
        <label>
          Find catalog book
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            maxLength={300}
          />
        </label>
        <button disabled={disabled || !input.trim()}>Find matching book</button>
      </form>
      <Notice error={books.error || versions.error} />
      {books.data && (
        <>
          <label>
            Catalog book
            <select
              value={workId}
              disabled={disabled}
              onChange={(event) => {
                setWorkId(event.target.value);
                setVersionId("");
                setVersionOffset(0);
                onChange(null);
              }}
            >
              <option value="">Choose a book</option>
              {books.data.items.map((book) => (
                <option key={book.id} value={book.id}>
                  {book.title} · {book.authors.join(", ")}
                </option>
              ))}
            </select>
          </label>
          <div className="actions">
            <button
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - 20))}
            >
              Previous matches
            </button>
            <button
              disabled={offset + 20 >= books.data.total}
              onClick={() => setOffset((value) => value + 20)}
            >
              More matches
            </button>
          </div>
        </>
      )}
      {versions.data && (
        <>
          <label>
            Catalog version
            <select
              value={versionId}
              disabled={disabled}
              onChange={(event) => update(event.target.value, full)}
            >
              <option value="">Choose the matching edition or recording</option>
              {versions.data.versions
                .filter(
                  (version) =>
                    version.medium === group.medium && !version.needs_review,
                )
                .map((version) => (
                  <option key={version.id} value={version.id}>
                    {version.title || group.title} ·{" "}
                    {version.narrators.join(", ") || version.medium} ·{" "}
                    {version.publication_year || "Year unknown"}
                    {version.owned ? " · Already in library" : ""}
                  </option>
                ))}
            </select>
          </label>
          <div className="actions">
            <button
              disabled={versionOffset === 0}
              onClick={() => {
                update("", full);
                setVersionOffset((value) => Math.max(0, value - 40));
              }}
            >
              Previous versions
            </button>
            <button
              disabled={versionOffset + 40 >= versions.data.versions_total}
              onClick={() => {
                update("", full);
                setVersionOffset((value) => value + 40);
              }}
            >
              More versions
            </button>
          </div>
          <label className="check-label">
            <input
              type="checkbox"
              checked={full}
              disabled={disabled}
              onChange={(event) => update(versionId, event.target.checked)}
            />
            These files contain the complete book, not a sample or companion
            document
          </label>
        </>
      )}
    </article>
  );
}
