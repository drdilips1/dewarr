import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  BookOpen,
  CheckCircle2,
  Folder,
  Headphones,
  LoaderCircle,
} from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import SettingHelp from "../components/SettingHelp";
import BookDialog from "../components/BookDialog";
import AutomaticImportPolicy from "./AutomaticImportPolicy";
import {
  useLibraryFolderSettings,
  selectLibraryDestination,
} from "./libraryFolderSettings";

type Destination = components["schemas"]["DestinationView"];

function libraryApp(kind?: string) {
  return kind === "grimmory" ? "Grimmory" : "Audiobookshelf";
}
type Medium = "ebook" | "audio";
const names = { ebook: "Ebooks", audio: "Audiobooks" };

export default function Destinations({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [editing, setEditing] = useState<Medium | null>(null);
  const query = useLibraryFolderSettings();
  const selected = (medium: Medium) =>
    selectLibraryDestination(
      query.data?.destinations || [],
      query.data?.defaults.effective?.[`${medium}_destination_id`],
      medium,
    );
  return (
    <div className="library-folder-settings">
      {!embedded && <h1>Library folders</h1>}
      <p className="muted">
        Choose an Audiobookshelf or Grimmory folder for each format. Your naming
        rules build the folders inside it; original downloads stay available for
        seeding.
      </p>
      <Notice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        query.data && (
          <div className="media-folder-list">
            {(["ebook", "audio"] as const).map((medium) => {
              const destination = selected(medium);
              const library = query.data.libraries.find(
                (l) => l.id === destination?.library_id,
              );
              return (
                <section
                  className="media-folder-card"
                  key={medium}
                  aria-label={`${names[medium]} destination`}
                >
                  <div className="media-folder-row">
                    {medium === "ebook" ? (
                      <BookOpen size={21} />
                    ) : (
                      <Headphones size={21} />
                    )}
                    <div className="media-folder-copy">
                      <h3>{names[medium]}</h3>
                      <p>
                        {destination
                          ? `${library?.name || "Library"} · ${libraryApp(destination.server_kind)}`
                          : "No folder selected"}
                      </p>
                      {destination && (
                        <code className="library-root-path">
                          {destination.backend_path}
                        </code>
                      )}
                      {destination?.local_path &&
                        destination.local_path !== destination.backend_path && (
                          <p className="library-local-path">
                            Dewarr sees <code>{destination.local_path}</code>
                          </p>
                        )}
                      {destination && (
                        <small
                          className={
                            destination.publication_available
                              ? "success"
                              : "muted"
                          }
                        >
                          {destination.publication_available &&
                          destination.mode === "hardlink" ? (
                            <>
                              <CheckCircle2 size={12} /> Hardlinks verified
                            </>
                          ) : destination.mode === "copy" ? (
                            "Copy mode · choose a folder to use hardlinks"
                          ) : (
                            "Needs verification"
                          )}
                        </small>
                      )}
                    </div>
                    <button
                      onClick={() => setEditing(medium)}
                      aria-label={`${destination ? "Change" : "Choose"} ${names[medium].toLowerCase()} folder`}
                    >
                      <Folder size={15} />
                      {destination ? "Change" : "Choose folder"}
                    </button>
                  </div>
                  {destination && (
                    <div className="media-folder-automation">
                      <AutomaticImportPolicy
                        destinationId={destination.id}
                        revision={destination.revision}
                        verified={destination.publication_available}
                        unsaved={false}
                      />
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )
      )}
      <div className="library-folder-guide">
        <p>
          <strong>Hardlinks save space.</strong> Downloads and library folders
          must share a filesystem. Changes to file contents affect both
          locations.
        </p>
        <div className="button-row">
          <Link to="/settings#naming">Edit file naming →</Link>
          <Link to="/settings#downloaders">Download paths &amp; mapping →</Link>
        </div>
      </div>
      {editing && (
        <FolderPicker
          medium={editing}
          saved={selected(editing)}
          close={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function FolderPicker({
  medium,
  saved,
  close,
}: {
  medium: Medium;
  saved?: Destination;
  close: () => void;
}) {
  const cache = useQueryClient();
  const current = useRef(saved);
  const [choice, setChoice] = useState(
    saved ? `${saved.library_id}|${saved.backend_path}` : "",
  );
  const [localPath, setLocalPath] = useState(
    saved?.local_path || saved?.backend_path || "",
  );
  const [otherPath, setOtherPath] = useState(
    !!saved?.local_path && saved.local_path !== saved.backend_path,
  );
  const [downloaderId, setDownloaderId] = useState("");
  const [automaticChoice, setAutomatic] = useState<boolean | null>(null);
  const policy = useQuery({
    queryKey: [
      "automatic-import-policy",
      saved?.id,
      saved?.revision,
      saved?.publication_available,
    ],
    enabled: !!saved,
    queryFn: async () =>
      result(
        await api.GET(
          "/api/organization/destinations/{destination_id}/automatic-import",
          { params: { path: { destination_id: saved!.id } } },
        ),
      ),
  });
  const automatic = automaticChoice ?? policy.data?.enabled ?? true;
  const [progress, setProgress] = useState("");
  const options = useQuery({
    queryKey: ["library-folder-options"],
    queryFn: async () => {
      const [libraries, downloaders] = await Promise.all([
        api.GET("/api/organization/library-folders").then(result),
        api.GET("/api/downloaders").then(result),
      ]);
      return {
        libraries,
        downloaders: downloaders.filter(
          (d) => d.enabled && d.status === "connected" && d.mappings_current,
        ),
      };
    },
  });
  const downloader =
    options.data?.downloaders.find((d) => d.id === downloaderId) ||
    (options.data?.downloaders.length === 1
      ? options.data.downloaders[0]
      : undefined);
  const folders = (options.data?.libraries || [])
    .filter((item) =>
      medium === "audio" ? item.audio_allowed : item.ebooks_allowed,
    )
    .flatMap((item) =>
      item.folders.map((path) => ({
        ...item,
        path,
        key: `${item.library_id}|${path}`,
      })),
    )
    .sort((a, b) =>
      medium === "audio"
        ? Number(a.ebooks_allowed) - Number(b.ebooks_allowed)
        : 0,
    );
  const selectedChoice = choice || folders[0]?.key || "";
  const selectedFolder = folders.find(
    (folder) => folder.key === selectedChoice,
  );
  const library = selectedFolder;
  const backendPath = selectedFolder?.path || "";
  const eligible = !!selectedFolder;
  const workerPath = otherPath ? localPath : backendPath;
  const save = useMutation({
    mutationFn: async () => {
      if (!library || !downloader || !eligible)
        throw new Error("Choose a folder and connect a download client first.");
      setProgress("Saving folder…");
      const destination = result(
        await api.PUT("/api/organization/library-folders/{medium}", {
          params: { path: { medium } },
          body: {
            library_id: library.library_id,
            backend_path: backendPath,
            local_path: workerPath,
            destination_id: current.current?.id,
            expected_revision: current.current?.revision,
          },
        }),
      );
      current.current = destination;
      setProgress(
        `Checking hardlinks and ${libraryApp(library.server_kind)} access…`,
      );
      const operation = result(
        await api.POST(
          "/api/organization/destinations/{destination_id}/setup-probe",
          {
            params: {
              path: { destination_id: destination.id },
              header: { "idempotency-key": crypto.randomUUID() },
            },
            body: {
              downloader_id: downloader.id,
              downloader_generation: downloader.generation,
              expected_revision: destination.revision,
            },
          },
        ),
      );
      for (let attempt = 0; attempt < 80; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const activity = result(await api.GET("/api/activity"));
        const status = activity.find((entry) => entry.id === operation.id);
        if (
          status?.status === "failed" ||
          status?.status === "needs-review" ||
          status?.status === "cancelled"
        )
          throw new Error(status.message || "Folder verification failed.");
        if (status?.status === "completed") {
          setProgress("Setting your library destination…");
          return result(
            await api.POST(
              "/api/organization/library-folders/{destination_id}/activate",
              {
                params: { path: { destination_id: destination.id } },
                body: { expected_revision: destination.revision, automatic },
              },
            ),
          );
        }
      }
      throw new Error(
        "The worker has not finished checking this folder. Check the download client and worker, then try again.",
      );
    },
    onSuccess: async () => {
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["library-folder-settings"] }),
        cache.invalidateQueries({ queryKey: ["download-defaults"] }),
        cache.invalidateQueries({ queryKey: ["selection-options"] }),
        cache.invalidateQueries({ queryKey: ["automatic-import-policy"] }),
      ]);
      close();
    },
    onSettled: () =>
      cache.invalidateQueries({ queryKey: ["library-folder-settings"] }),
  });
  return (
    <BookDialog
      title={`Choose ${names[medium].toLowerCase()} folder`}
      close={() => {
        if (!save.isPending) close();
      }}
      className="folder-picker-dialog"
    >
      <div className="settings-section-body folder-picker-body">
        <p className="muted">
          Start with your library folder. If Dewarr uses a different mount path,
          choose Other path to map the same folder.
        </p>
        <Notice error={options.error} />
        {options.isPending && <Loading />}
        {options.data && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate();
            }}
          >
            <fieldset className="abs-folder-options" disabled={save.isPending}>
              <legend className="sr-only">Destination path</legend>
              {folders.map((folder, index) => (
                <label className="abs-folder-option" key={folder.key}>
                  <input
                    type="radio"
                    name="folder"
                    aria-label={`${folder.library_name}: ${folder.path}`}
                    checked={!otherPath && selectedChoice === folder.key}
                    onChange={() => {
                      setChoice(folder.key);
                      setOtherPath(false);
                    }}
                  />
                  <span className="folder-option-copy">
                    <span className="folder-option-title">
                      {folders.length === 1
                        ? `${libraryApp(folder.server_kind)} folder`
                        : folder.library_name}
                      {index === 0 && <small>Default</small>}
                    </span>
                    <span className="folder-option-path">{folder.path}</span>
                  </span>
                </label>
              ))}
              {!!folders.length && (
                <label className="abs-folder-option folder-other-option">
                  <input
                    type="radio"
                    name="folder"
                    aria-label="Other path"
                    checked={otherPath}
                    onChange={() => {
                      setChoice(selectedChoice);
                      setOtherPath(true);
                      if (!localPath) setLocalPath(backendPath);
                    }}
                  />
                  <span className="folder-option-copy">
                    <span className="folder-option-title">Other path</span>
                  </span>
                </label>
              )}
              {otherPath && !!folders.length && (
                <div className="folder-other-field">
                  <label>
                    <span className="sr-only">Dewarr folder path</span>
                    <input
                      value={localPath}
                      onChange={(event) => setLocalPath(event.target.value)}
                      placeholder="/data/library/ebooks"
                      required
                    />
                  </label>
                  <p className="muted">
                    Same library folder, using its path in Dewarr.
                  </p>
                  {folders.length > 1 && (
                    <p className="muted">
                      {selectedFolder?.library_name} · {backendPath}
                    </p>
                  )}
                </div>
              )}
              {!folders.length && (
                <p className="muted">
                  {options.data.libraries.length
                    ? "No compatible folders found. Check the library settings."
                    : "Connect Audiobookshelf or Grimmory to choose a folder."}
                </p>
              )}
              {options.data.libraries
                .filter((item) => item.error)
                .map((item) => (
                  <p className="notice error" key={item.library_id}>
                    {item.library_name}: {item.error}
                  </p>
                ))}
              {choice && !eligible && (
                <p className="notice">
                  The saved folder is no longer available. Choose another
                  library folder.
                </p>
              )}
            </fieldset>
            {options.data.downloaders.length > 1 && (
              <label>
                Download client
                <select
                  value={downloaderId}
                  onChange={(e) => setDownloaderId(e.target.value)}
                  disabled={save.isPending}
                >
                  <option value="">Choose a client</option>
                  {options.data.downloaders.map((d) => (
                    <option value={d.id} key={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {!options.data.downloaders.length && (
              <p className="notice">
                Set up a{" "}
                <Link to="/settings#downloaders" onClick={close}>
                  download client
                </Link>{" "}
                to verify hardlinks.
              </p>
            )}
            <label className="check-label">
              <input
                type="checkbox"
                checked={automatic}
                onChange={(e) => setAutomatic(e.target.checked)}
                disabled={save.isPending}
              />
              Auto-organize downloads
              <SettingHelp label="automatic organization">
                Hardlink completed downloads into this folder using your file
                naming settings. Originals stay available for seeding. Uncertain
                matches stay in review.
              </SettingHelp>
            </label>
            <Notice error={save.error || policy.error} />
            {save.isPending && (
              <p role="status" className="folder-save-progress">
                <LoaderCircle size={15} />
                {progress}
              </p>
            )}
            <footer className="folder-picker-footer">
              <button type="button" disabled={save.isPending} onClick={close}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={
                  save.isPending ||
                  (!!saved && !policy.data) ||
                  !eligible ||
                  !downloader ||
                  !workerPath.trim()
                }
              >
                {save.isPending ? "Checking…" : "Use this folder"}
              </button>
            </footer>
          </form>
        )}
      </div>
    </BookDialog>
  );
}
