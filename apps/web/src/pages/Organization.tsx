import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Profile = components["schemas"]["NamingProfile"];
type Settings = components["schemas"]["SettingsView"];
type Template =
  "audio_folder" | "ebook_folder" | "audio_filename" | "ebook_filename";
const fields: [Template, string][] = [
  ["audio_folder", "Audiobook folder"],
  ["audio_filename", "Audiobook filename"],
  ["ebook_folder", "Ebook folder"],
  ["ebook_filename", "Ebook filename"],
];

export default function Organization() {
  const query = useQuery({
    queryKey: ["organization"],
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const [settings, defaults] = await Promise.all([
        api.GET("/api/organization/settings").then(result),
        api.GET("/api/organization/defaults").then(result),
      ]);
      return { settings, defaults };
    },
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <Notice error={query.error} />;
  return (
    <Editor
      key={query.data.settings.revision}
      settings={query.data.settings}
      defaults={query.data.defaults}
    />
  );
}

function Editor({
  settings,
  defaults,
}: {
  settings: Settings;
  defaults: Profile;
}) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState(settings.profile);
  const [previewProfile, setPreviewProfile] = useState(draft);
  const [field, setField] = useState<Template>("audio_folder");
  const [token, setToken] = useState("title");
  const inputs = useRef<Partial<Record<Template, HTMLInputElement | null>>>({});
  useEffect(() => {
    const timer = window.setTimeout(() => setPreviewProfile(draft), 350);
    return () => window.clearTimeout(timer);
  }, [draft]);
  const preview = useQuery({
    queryKey: ["organization-preview", previewProfile],
    retry: false,
    queryFn: async () =>
      result(
        await api.POST("/api/organization/preview", {
          body: { profile: previewProfile },
        }),
      ),
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/organization/settings", {
          body: { profile: draft, expected_revision: settings.revision },
        }),
      ),
    onSuccess: (settings) =>
      cache.setQueryData(["organization"], { settings, defaults }),
  });
  const changed = JSON.stringify(draft) !== JSON.stringify(settings.profile);
  const currentPreview =
    JSON.stringify(previewProfile) === JSON.stringify(draft);
  function insertToken() {
    const input = inputs.current[field];
    const value = draft[field] || "";
    const start = input?.selectionStart ?? value.length;
    const end = input?.selectionEnd ?? value.length;
    const text = `{${token}}`;
    setDraft({
      ...draft,
      [field]: value.slice(0, start) + text + value.slice(end),
    });
    requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + text.length, start + text.length);
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Library setup</p>
          <h1>File organization</h1>
          <p className="muted">
            Choose how future books and recordings will be named. Existing files
            stay in place.
          </p>
        </div>
      </div>
      <p className="notice">
        Naming previews and completed-file inspection are available. Library
        destination checks are available; file publication is still being built.
      </p>
      <p>
        <Link to="/organization/inspections">Inspect completed downloads</Link>
      </p>
      <p>
        <Link to="/organization/destinations">
          Configure library destinations
        </Link>
      </p>
      <section className="panel editor" aria-label="Organization settings">
        <h2>Folder layout</h2>
        <label>
          Layout preset
          <select
            value={draft.layout}
            disabled={save.isPending}
            onChange={(event) =>
              setDraft({
                ...draft,
                layout: event.target.value as Profile["layout"],
              })
            }
          >
            <option value="conventional">
              Author / series / book and version
            </option>
            <option value="nested">
              Author / series / book / version — preview only
            </option>
          </select>
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={draft.rename_files}
            disabled={save.isPending}
            onChange={(event) =>
              setDraft({ ...draft, rename_files: event.target.checked })
            }
          />
          Rename imported files
        </label>
        <p className="muted">
          Each recording or edition has its own item folder. Ebook and audiobook
          paths use separate illustrative roots below.
        </p>
        <details>
          <summary>Customize naming</summary>
          <p className="muted">
            Insert metadata tokens into the folder or filename. Optional
            segments such as <code>[ - {"{edition_year}"}]</code> disappear when
            metadata is missing. Actual file extensions are added automatically.
          </p>
          {fields.map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                ref={(element) => {
                  inputs.current[key] = element;
                }}
                value={draft[key]}
                maxLength={600}
                disabled={save.isPending}
                onFocus={() => setField(key)}
                onChange={(event) =>
                  setDraft({ ...draft, [key]: event.target.value })
                }
              />
            </label>
          ))}
          <div className="inline-form">
            <label>
              Insert into
              <select
                value={field}
                onChange={(event) => setField(event.target.value as Template)}
              >
                {fields.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Metadata token
              <select
                value={token}
                onChange={(event) => setToken(event.target.value)}
              >
                {Object.entries(settings.tokens).map(([key, description]) => (
                  <option key={key} value={key}>
                    {key} — {description}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={save.isPending}
              onClick={insertToken}
            >
              Insert token
            </button>
          </div>
        </details>
        <Notice error={save.error || preview.error} />
        <div className="button-row">
          <button
            type="button"
            onClick={() => setDraft(defaults)}
            disabled={save.isPending}
          >
            Reset naming defaults
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => save.mutate()}
            disabled={
              !changed ||
              save.isPending ||
              !currentPreview ||
              preview.isFetching ||
              !!preview.error
            }
          >
            {save.isPending ? "Saving…" : "Save naming settings"}
          </button>
        </div>
        {!changed && (
          <p className="success" role="status">
            Naming settings are saved.
          </p>
        )}
      </section>
      <section className="library-access" aria-label="Naming examples">
        <h2>Preview with example books</h2>
        <p className="muted">
          Synthetic examples include a series download, two narrators, a
          multi-track audiobook and missing metadata. These are not books in
          your library.
        </p>
        {preview.isFetching && <p className="muted">Updating the preview…</p>}
        {preview.data && (
          <>
            <p role="status">
              {preview.data.expected_items} planned item folders ·{" "}
              {preview.data.held_items} need attention
            </p>
            {preview.data.items.map((item) => (
              <article className="panel editor" key={item.group_id}>
                <h3>
                  {item.title} ·{" "}
                  {item.medium === "audio" ? "Audiobook" : "Ebook"}
                </h3>
                {item.reason && <p className="notice">{item.reason}</p>}
                {!!item.missing_metadata?.length && (
                  <p className="muted">
                    Missing metadata: {item.missing_metadata?.join(", ")}.
                    Optional segments are omitted.
                  </p>
                )}
                {(item.warnings ?? []).map((warning) => (
                  <p className="notice" key={warning}>
                    {warning}
                  </p>
                ))}
                {(item.files ?? []).map((file) => (
                  <div className="import-path" key={file.source}>
                    <span className="muted">Download: {file.source}</span>
                    <strong>Library: {file.destination}</strong>
                  </div>
                ))}
              </article>
            ))}
          </>
        )}
      </section>
    </>
  );
}
