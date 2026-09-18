import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import AutomaticImportPolicy from "./AutomaticImportPolicy";

type Destination = components["schemas"]["DestinationView"];
type Library = components["schemas"]["LibraryView"];

export default function Destinations() {
  const [params] = useSearchParams();
  const planId = params.get("plan");
  const query = useQuery({
    queryKey: ["destination-setup"],
    queryFn: async () => {
      const [roots, libraries, destinations] = await Promise.all([
        api.GET("/api/organization/destination-roots").then(result),
        api.GET("/api/library/libraries").then(result),
        api.GET("/api/organization/destinations").then(result),
      ]);
      return { roots, libraries, destinations };
    },
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <Notice error={query.error} />;
  return (
    <>
      <Link to="/organization">← Naming settings</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Library setup</p>
          <h1>Library destinations</h1>
          <p className="muted">
            Choose where future ebook and audiobook items will be organized.
          </p>
        </div>
      </div>
      <p className="notice">
        Verify the filesystem route and Audiobookshelf folder mapping before
        importing a saved plan. Each book is confirmed in Audiobookshelf after
        publication.
      </p>
      {!query.data.roots.length && (
        <p className="notice">
          Configure BOOK_IMPORT_DESTINATIONS and a private
          BOOK_IMPORT_STAGING_ROOT on the worker to add a destination.
        </p>
      )}
      {!planId && (
        <p className="muted">
          To test the hardlink route with a real source file, open a saved
          import plan and choose Check destination.
        </p>
      )}
      {query.data.roots.map((root) => {
        const saved = query.data.destinations.find(
          (row) => row.root_key === root,
        );
        return (
          <DestinationEditor
            key={`${root}:${saved?.revision || "new"}`}
            root={root}
            saved={saved}
            libraries={query.data.libraries}
            planId={planId}
          />
        );
      })}
    </>
  );
}

function DestinationEditor({
  root,
  saved,
  libraries,
  planId,
}: {
  root: string;
  saved?: Destination;
  libraries: Library[];
  planId: string | null;
}) {
  const cache = useQueryClient();
  const [libraryId, setLibraryId] = useState(saved?.library_id || "");
  const [medium, setMedium] = useState<"ebook" | "audio">(
    (saved?.medium as "ebook" | "audio") || "ebook",
  );
  const [mode, setMode] = useState<"hardlink" | "copy">(
    (saved?.mode as "hardlink" | "copy") || "hardlink",
  );
  const [backendPath, setBackendPath] = useState(saved?.backend_path || "");
  const [enabled, setEnabled] = useState(saved?.enabled ?? true);
  const [operationId, setOperationId] = useState<string | null>(null);
  const attempt = useRef<{ payload: string; key: string } | null>(null);
  const status = useQuery({
    queryKey: ["destination-operation", operationId],
    enabled: !!operationId,
    queryFn: async () => {
      const [activity, destinations] = await Promise.all([
        api.GET("/api/activity").then(result),
        api.GET("/api/organization/destinations").then(result),
      ]);
      return {
        operation: activity.find((row) => row.id === operationId),
        destination: destinations.find((row) => row.id === saved?.id),
      };
    },
    refetchInterval: (query) =>
      !query.state.data ||
      ["queued", "running"].includes(query.state.data.operation?.status || "")
        ? 1500
        : false,
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/organization/destinations/{root_key}", {
          params: { path: { root_key: root } },
          body: {
            library_id: libraryId,
            medium,
            mode,
            backend_path: backendPath,
            enabled,
            expected_revision: saved?.revision,
          },
        }),
      ),
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["destination-setup"] }),
  });
  const probe = useMutation({
    mutationFn: async () => {
      const payload = JSON.stringify([saved!.id, planId, saved!.revision]);
      if (attempt.current?.payload !== payload) {
        attempt.current = { payload, key: crypto.randomUUID() };
      }
      return result(
        await api.POST(
          "/api/organization/destinations/{destination_id}/probe",
          {
            params: {
              path: { destination_id: saved!.id },
              header: { "idempotency-key": attempt.current.key },
            },
            body: { plan_id: planId!, expected_revision: saved!.revision },
          },
        ),
      );
    },
    onSuccess: (operation) => {
      setOperationId(operation.id);
      attempt.current = null;
    },
  });
  const changed =
    !saved ||
    saved.library_id !== libraryId ||
    saved.medium !== medium ||
    saved.mode !== mode ||
    saved.backend_path !== backendPath ||
    saved.enabled !== enabled;
  const busy =
    save.isPending ||
    probe.isPending ||
    (operationId &&
      (!status.data ||
        ["queued", "running"].includes(status.data.operation?.status || "")));
  const report = status.data?.destination?.probe || saved?.probe;
  return (
    <section className="panel editor" aria-label={`Destination ${root}`}>
      <h2>{root}</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label>
          Audiobookshelf library
          <select
            value={libraryId}
            disabled={!!busy}
            onChange={(event) => setLibraryId(event.target.value)}
            required
          >
            <option value="">Choose a library</option>
            {libraries
              .filter((library) => library.accessible)
              .map((library) => (
                <option key={library.id} value={library.id}>
                  {library.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Media type
          <select
            value={medium}
            disabled={!!busy}
            onChange={(event) =>
              setMedium(event.target.value as "ebook" | "audio")
            }
          >
            <option value="ebook">Ebooks</option>
            <option value="audio">Audiobooks</option>
          </select>
        </label>
        <label>
          Audiobookshelf folder path
          <input
            value={backendPath}
            maxLength={1024}
            disabled={!!busy}
            onChange={(event) => setBackendPath(event.target.value)}
            placeholder="/books"
            required
          />
        </label>
        <p className="muted">
          The absolute folder root configured in Audiobookshelf. The test
          verifies that Audiobookshelf and the worker see the same directory.
        </p>
        <label>
          Import method
          <select
            value={mode}
            disabled={!!busy}
            onChange={(event) =>
              setMode(event.target.value as "hardlink" | "copy")
            }
          >
            <option value="hardlink">Hardlink required</option>
            <option value="copy">Copy files — uses additional storage</option>
          </select>
        </label>
        <p className="muted">
          Hardlinks keep the original download in place. An unavailable hardlink
          route will not silently switch to copying.
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            checked={enabled}
            disabled={!!busy}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          Destination enabled
        </label>
        <Notice error={save.error} />
        <button
          className="primary"
          disabled={!!busy || !changed || !libraryId || !backendPath}
        >
          {save.isPending ? "Saving…" : "Save destination"}
        </button>
      </form>
      {saved && (
        <AutomaticImportPolicy
          destinationId={saved.id}
          revision={saved.revision}
          verified={
            (status.data?.destination || saved).publication_available ?? false
          }
          unsaved={changed || !!busy}
        />
      )}
      <div className="form-actions">
        <button
          disabled={
            !!busy || changed || !saved?.configured || !enabled || !planId
          }
          onClick={() => probe.mutate()}
        >
          Test destination route
        </button>
      </div>
      <p className="muted">
        The test creates and removes its own temporary files and empty folders.
        It checks the selected file's link route and verifies the folder mapping
        through Audiobookshelf. The ABS connection needs upload permission for
        its path check; no book is uploaded.
      </p>
      <Notice error={probe.error || status.error} />
      {status.data?.operation &&
        status.data.operation.message !== report?.message && (
          <p role="status">{status.data.operation.message}</p>
        )}
      {report && (
        <p className={report.status === "verified" ? "success" : "notice"}>
          {String(report.message)}
        </p>
      )}
      {changed && (
        <p className="muted">Save changes before testing this destination.</p>
      )}
    </section>
  );
}
