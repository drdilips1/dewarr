import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import { BookOpen, Headphones, Folder, FileText } from "lucide-react";
import Sortable from "../components/Sortable";
import { Link } from "react-router-dom";
import {
  useLibraryFolderSettings,
  selectLibraryDestination,
} from "./libraryFolderSettings";
import SettingHelp from "../components/SettingHelp";
import {
  folderTemplate,
  templateSegments,
  toggleSegment,
  readChoices,
  simpleChoices,
  seriesChoices,
  namingExamples,
  seriesIndexFilename,
  seriesIndexFolder,
  parseSegment,
  withJoin,
  type Medium,
  type NamingChoices,
  type TokenJoin,
} from "./namingBuilder";

type Profile = components["schemas"]["NamingProfile"];
type Settings = components["schemas"]["SettingsView"];
export default function Organization({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [medium, setMedium] = useState<Medium>("ebook");
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
      embedded={embedded}
      medium={medium}
      setMedium={setMedium}
      key={query.data.settings.revision}
      settings={query.data.settings}
      defaults={query.data.defaults}
    />
  );
}

function Editor({
  embedded,
  settings,
  defaults,
  medium,
  setMedium,
}: {
  embedded: boolean;
  settings: Settings;
  defaults: Profile;
  medium: Medium;
  setMedium: (medium: Medium) => void;
}) {
  const cache = useQueryClient();
  const folders = useLibraryFolderSettings();
  const [draft, setDraft] = useState(settings.profile);
  const [previewProfile, setPreviewProfile] = useState(draft);
  useEffect(() => {
    const timer = window.setTimeout(() => setPreviewProfile(draft), 250);
    return () => window.clearTimeout(timer);
  }, [draft]);
  const preview = useQuery({
    queryKey: ["organization-preview", "builder", previewProfile],
    retry: false,
    placeholderData: (previous) => previous,
    queryFn: async () =>
      result(
        await api.POST("/api/organization/preview", {
          body: { profile: previewProfile, groups: namingExamples },
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
  const folder = `${medium}_folder` as const;
  const filename = `${medium}_filename` as const;
  const choices = readChoices(draft[folder], medium);
  const changed = JSON.stringify(draft) !== JSON.stringify(settings.profile);
  const current =
    JSON.stringify(previewProfile) === JSON.stringify(draft) &&
    !preview.isFetching;
  const example = preview.data?.items.find((item) => item.medium === medium);
  const path = example?.files?.[0]?.destination;
  const destination = selectLibraryDestination(
    folders.data?.destinations || [],
    folders.data?.defaults.effective?.[`${medium}_destination_id`],
    medium,
  );
  // The planner returns an illustrative media root; substitute only that root.
  const relativePath = path?.split("/").slice(1).join("/");
  const fullPath = relativePath
    ? `${destination?.backend_path?.replace(/\/$/, "") || (medium === "audio" ? "audiobooks" : "ebooks")}/${relativePath}`
    : undefined;
  const options: [keyof NamingChoices, string][] = [
    ["author", "Author"],
    ["series", "Series"],
    ["sequence", "Sequence"],
    ["year", medium === "audio" ? "Recording year" : "Edition year"],
    ["version", medium === "audio" ? "Narrator" : "Edition"],
    ["language", "Language"],
    ["publisher", "Publisher"],
  ];
  const presets = [
    ["By author", simpleChoices],
    ["By series", seriesChoices],
  ] as const;
  return (
    <section className="naming-builder" aria-label="Organization settings">
      {!embedded && <h1>File naming</h1>}
      <div className="segmented-control" role="group" aria-label="Book format">
        <button
          type="button"
          aria-pressed={medium === "ebook"}
          onClick={() => setMedium("ebook")}
        >
          <BookOpen size={16} />
          Ebook
        </button>
        <button
          type="button"
          aria-pressed={medium === "audio"}
          onClick={() => setMedium("audio")}
        >
          <Headphones size={16} />
          Audiobook
        </button>
      </div>
      <div className="naming-workspace">
        <div className="naming-options">
          <fieldset>
            <legend>Layout preset</legend>
            <div className="preset-options">
              <button
                type="button"
                disabled={save.isPending}
                aria-pressed={
                  draft.layout === defaults.layout &&
                  draft[folder] === defaults[folder]
                }
                onClick={() =>
                  setDraft({
                    ...draft,
                    layout: defaults.layout,
                    [folder]: defaults[folder],
                  })
                }
              >
                Recommended
              </button>
              {presets.map(([name, preset]) => (
                <button
                  key={name}
                  type="button"
                  aria-pressed={
                    draft.layout === "conventional" &&
                    draft[folder] === folderTemplate(medium, preset)
                  }
                  disabled={save.isPending}
                  onClick={() =>
                    setDraft({
                      ...draft,
                      layout: "conventional",
                      [folder]: folderTemplate(medium, preset),
                    })
                  }
                >
                  {name}
                </button>
              ))}
              <button
                type="button"
                aria-pressed={
                  draft.layout === "conventional" &&
                  draft[folder] === seriesIndexFolder &&
                  draft[filename] === seriesIndexFilename
                }
                disabled={save.isPending}
                title="Author/Series/Sequence Title, with file Sequence - Series - Title (Year)"
                onClick={() =>
                  setDraft({
                    ...draft,
                    layout: "conventional",
                    [folder]: seriesIndexFolder,
                    [filename]: seriesIndexFilename,
                  })
                }
              >
                Sequence title
              </button>
            </div>
          </fieldset>
          {choices && draft.layout === "conventional" ? (
            <fieldset>
              <legend>Include in path</legend>
              <div className="metadata-toggles">
                <label className="check-label">
                  <input type="checkbox" checked disabled />
                  Title
                </label>
                {options.map(([key, label]) => (
                  <label className="check-label" key={key}>
                    <input
                      type="checkbox"
                      checked={choices[key]}
                      disabled={save.isPending}
                      onChange={() =>
                        setDraft({
                          ...draft,
                          [folder]: toggleSegment(draft[folder], medium, key),
                        })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="notice">
              Custom layout active. Choose a preset to use the path builder.
            </p>
          )}
          <div className="naming-file-controls">
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
              <SettingHelp label="renaming files">
                Applies to both ebooks and audiobooks. Original torrent files
                keep their names for seeding; only library filenames change.
                Multi-file audiobooks need disc and track in the filename so
                playback order is preserved.
              </SettingHelp>
            </label>
            {draft.rename_files && (
              <label className="naming-filename-style">
                Filename style
                <select
                  value={
                    [
                      "{title}",
                      "[{sequence} - ]{title}",
                      ...(medium === "audio"
                        ? ["[{disc}-][{track} - ]{title}"]
                        : []),
                      "{author} - {title}",
                      seriesIndexFilename,
                    ].includes(draft[filename])
                      ? draft[filename]
                      : "custom"
                  }
                  disabled={save.isPending}
                  onChange={(event) => {
                    if (event.target.value !== "custom")
                      setDraft({ ...draft, [filename]: event.target.value });
                  }}
                >
                  <option value="{title}">Book title</option>
                  <option value="[{sequence} - ]{title}">
                    Sequence · Book title
                  </option>
                  {medium === "audio" && (
                    <option value="[{disc}-][{track} - ]{title}">
                      Disc · Track · Book title
                    </option>
                  )}
                  <option value="{author} - {title}">
                    Author · Book title
                  </option>
                  <option value={seriesIndexFilename}>
                    Sequence · Series · Title (Year)
                  </option>
                  <option value="custom" disabled>
                    Custom template
                  </option>
                </select>
              </label>
            )}
          </div>
          {draft.rename_files && (
            <div className="naming-path-editor">
              <div className="naming-lane-heading">
                <h3>Filename order</h3>
                <span>Drag to reorder</span>
              </div>
              <TokenLane
                template={draft[filename]}
                label="Filename token order"
                allowFolder={false}
                disabled={save.isPending}
                onChange={(value) => setDraft({ ...draft, [filename]: value })}
              />
            </div>
          )}
          <div className="naming-path-editor">
            <div className="naming-lane-heading">
              <h3>Folder order</h3>
              <span>Drag to reorder</span>
            </div>
            {folders.error && (
              <p className="muted">
                Library folder unavailable. The preview uses an example root.
              </p>
            )}
            <TokenLane
              template={draft[folder]}
              label="Folder token order"
              allowFolder
              disabled={save.isPending || draft.layout !== "conventional"}
              onChange={(value) => setDraft({ ...draft, [folder]: value })}
            />
          </div>
          <div
            className="folder-preview"
            aria-label="Folder preview"
            aria-busy={!current}
          >
            <div className="folder-preview-heading">
              <span className="setting-subheading">
                LIVE PREVIEW{" "}
                <SettingHelp label="naming preview">
                  Illustrative metadata and folders. Actual paths use the
                  selected library folder and the book’s available metadata.
                  Extensions are added automatically.
                </SettingHelp>
              </span>
              <span>{medium === "audio" ? "Audiobook" : "Ebook"}</span>
            </div>
            {fullPath && (
              <div
                className="naming-full-path"
                tabIndex={0}
                aria-label="Example destination path"
              >
                <code>{fullPath}</code>
              </div>
            )}
            {!path && (
              <p>
                {preview.isFetching
                  ? "Building preview…"
                  : example?.reason || "Preview unavailable"}
              </p>
            )}
            {!current && path && (
              <span className="preview-updating">Updating…</span>
            )}
            {example?.warnings?.map((warning) => (
              <p className="notice" key={warning}>
                {warning}
              </p>
            ))}
          </div>
          {path && (
            <section className="naming-tree-section" aria-label="Folder tree">
              <h3>Folder tree</h3>
              <ol className="folder-tree">
                <li>
                  <Folder size={14} />
                  <code>
                    {destination?.backend_path ||
                      (medium === "audio" ? "audiobooks" : "ebooks")}
                  </code>
                  <Link to="/settings#libraries">Change folder</Link>
                </li>
                {relativePath?.split("/").map((part, index, parts) => (
                  <li
                    key={index}
                    style={{ paddingInlineStart: `${(index + 1) * 12}px` }}
                  >
                    {index === parts.length - 1 ? (
                      <FileText size={14} />
                    ) : (
                      <Folder size={14} />
                    )}
                    <span>{part}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </div>
      <Notice error={save.error || preview.error} />
      <div className="settings-form-footer">
        <div className="button-row">
          <button
            type="button"
            className="primary"
            disabled={
              !changed ||
              save.isPending ||
              !current ||
              !!preview.error ||
              !preview.data?.items.length ||
              preview.data.items.some((item) => item.state !== "ready")
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save naming settings"}
          </button>
          <button
            type="button"
            disabled={save.isPending}
            onClick={() => setDraft(defaults)}
          >
            Reset naming defaults
          </button>
        </div>
        <span className="save-state" role="status">
          {changed ? "Unsaved changes" : "Saved"}
        </span>
      </div>
    </section>
  );
}

const tokenLabels: Record<string, string> = {
  author: "Author",
  title: "Title",
  series: "Series",
  sequence: "Sequence",
  recording_year: "Recording year",
  edition_year: "Edition year",
  narrator: "Narrator",
  edition: "Edition",
  language: "Language",
  publisher: "Publisher",
  disc: "Disc",
  track: "Track",
  year: "Year",
};
const joinLabels: [TokenJoin, string][] = [
  ["folder", "Folder"],
  ["dash", "Dash"],
  ["space", "Space"],
  ["parentheses", "Parentheses"],
];
function TokenLane({
  template,
  label,
  disabled,
  allowFolder,
  onChange,
}: {
  template: string;
  label: string;
  disabled: boolean;
  allowFolder: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="naming-token-lane">
      <Sortable
        horizontal
        label={label}
        disabled={disabled}
        values={templateSegments(template)}
        onChange={(segments) => onChange(segments.join(""))}
        render={(segment) => {
          const parsed = parseSegment(segment);
          const token =
            parsed?.token || segment.match(/\{([^}]+)\}/)?.[1] || "";
          const name =
            tokenLabels[token] || token.replaceAll("_", " ") || "Custom text";
          const join = parsed?.join ? (
            <select
              className="naming-token-join"
              aria-label={`Join ${name} in ${label}`}
              value={parsed.join}
              disabled={disabled}
              onPointerDown={(event) => event.stopPropagation()}
              onChange={(event) => {
                const next = withJoin(segment, event.target.value as TokenJoin);
                onChange(
                  templateSegments(template)
                    .map((item) => (item === segment ? next : item))
                    .join(""),
                );
              }}
            >
              {joinLabels
                .filter(([value]) => allowFolder || value !== "folder")
                .map(([value, joinName]) => (
                  <option key={value} value={value}>
                    {joinName}
                  </option>
                ))}
            </select>
          ) : null;
          return (
            <>
              {parsed?.leading && join}
              <span className="naming-token-label">{name}</span>
              {parsed && !parsed.leading && join}
            </>
          );
        }}
      />
    </div>
  );
}
