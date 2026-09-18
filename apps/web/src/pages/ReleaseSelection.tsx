import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Artifact = components["schemas"]["SourceArtifactView"];

export default function ReleaseSelection({ artifact }: { artifact: Artifact }) {
  const [params] = useSearchParams();
  const cache = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [choice, setChoice] = useState(
    params.get("request")
      ? `${params.get("request")}:${params.get("slot") || artifact.release.medium}`
      : "",
  );
  const [downloaderId, setDownloaderId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const key = useRef(crypto.randomUUID());
  const downloadKeys = useRef(new Map<string, string>());
  const options = useQuery({
    queryKey: ["selection-options"],
    queryFn: async () =>
      result(await api.GET("/api/acquisition/selections/options")),
  });
  const requests = useQuery({
    queryKey: ["requests", "selection", offset],
    queryFn: async () =>
      result(
        await api.GET("/api/requests", {
          params: { query: { offset, limit: 20 } },
        }),
      ),
  });
  const linkedRequest = useQuery({
    queryKey: ["requests", "selection-linked", params.get("request")],
    queryFn: async () =>
      result(
        await api.GET("/api/requests/{intent_id}", {
          params: { path: { intent_id: params.get("request")! } },
        }),
      ),
    enabled: !!params.get("request"),
  });
  const history = useQuery({
    queryKey: ["release-selections", artifact.id, historyOffset],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/selections", {
          params: {
            query: {
              artifact_id: artifact.id,
              offset: historyOffset,
              limit: 10,
            },
          },
        }),
      ),
  });
  const choices = Array.from(
    new Map(
      [
        ...(requests.data?.items || []),
        ...(linkedRequest.data ? [linkedRequest.data] : []),
      ].map((item) => [item.id, item]),
    ).values(),
  ).flatMap((intent) =>
    intent.targets
      .filter(
        (target) =>
          target.state === "wanted" &&
          (target.slot === artifact.release.medium || target.slot === "either"),
      )
      .map((target) => ({
        intent,
        target,
        value: `${intent.id}:${target.slot}`,
      })),
  );
  const selected = choices.find((item) => item.value === choice);
  const downloaders =
    options.data?.downloaders.filter((item) => item.ready) || [];
  const downloader =
    downloaders.find((item) => item.id === downloaderId) ||
    (downloaders.length === 1 ? downloaders[0] : undefined);
  const requiredLibrary =
    selected?.intent.specification[
      artifact.release.medium === "audio"
        ? "audio_library_id"
        : "ebook_library_id"
    ];
  const destinations =
    options.data?.destinations.filter(
      (item) =>
        item.ready &&
        item.medium === artifact.release.medium &&
        item.source_key === downloader?.source_key &&
        (!requiredLibrary || item.library_id === requiredLibrary),
    ) || [];
  const destination =
    destinations.find((item) => item.id === destinationId) ||
    (destinations.length === 1 ? destinations[0] : undefined);
  const refresh = async () => {
    await Promise.all(
      [
        "requests",
        "release-selections",
        "selection-options",
        "downloads",
        "activity",
      ].map((name) => cache.invalidateQueries({ queryKey: [name] })),
    );
  };
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/acquisition/selections", {
          params: { header: { "idempotency-key": key.current } },
          body: {
            intent_id: selected!.intent.id,
            slot: selected!.target.slot as "audio" | "ebook" | "either",
            artifact_id: artifact.id,
            downloader_id: downloader!.id,
            downloader_generation: downloader!.generation,
            destination_id: destination!.id,
            destination_revision: destination!.revision,
            confirmed_work_id: selected!.intent.work_id,
          },
        }),
      ),
    onSuccess: async () => {
      key.current = crypto.randomUUID();
      setConfirmed(false);
      await refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.DELETE("/api/acquisition/selections/{selection_id}", {
          params: { path: { selection_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  const startDownload = useMutation({
    mutationFn: async (id: string) => {
      if (!downloadKeys.current.has(id))
        downloadKeys.current.set(id, crypto.randomUUID());
      return result(
        await api.POST("/api/acquisition/downloads", {
          params: {
            header: { "idempotency-key": downloadKeys.current.get(id)! },
          },
          body: { selection_id: id },
        }),
      );
    },
    onSuccess: refresh,
  });
  const changed = () => {
    setConfirmed(false);
    key.current = crypto.randomUUID();
    save.reset();
  };
  return (
    <section
      className="panel editor library-access"
      aria-label="Release selection"
    >
      <h2>Select for a book request</h2>
      <p className="muted">
        Choose the book this release contains and its library destination. The
        whole torrent is selected; each book and version will need file
        inspection before import. Saving this choice does not start a download.
      </p>
      <Notice
        error={
          options.error ||
          requests.error ||
          linkedRequest.error ||
          history.error ||
          save.error ||
          cancel.error ||
          startDownload.error
        }
      />
      <label>
        Wanted book
        <select
          value={choice}
          onChange={(event) => {
            changed();
            setChoice(event.target.value);
          }}
        >
          <option value="">Choose a saved request</option>
          {choices.map((item) => (
            <option key={item.value} value={item.value}>
              {item.intent.work_title} ·{" "}
              {item.target.slot === "audio"
                ? "Audiobook"
                : item.target.slot === "ebook"
                  ? "Ebook"
                  : "Either medium"}{" "}
              · {item.intent.description}
            </option>
          ))}
        </select>
      </label>
      {(offset > 0 || (requests.data?.total || 0) > 20) && (
        <div className="button-row">
          {offset > 0 && (
            <button onClick={() => setOffset((value) => value - 20)}>
              Previous wanted books
            </button>
          )}
          {requests.data && offset + 20 < requests.data.total && (
            <button onClick={() => setOffset((value) => value + 20)}>
              More wanted books
            </button>
          )}
        </div>
      )}
      {!choices.length && !requests.isPending && (
        <p className="muted">
          No matching wanted requests on this page.{" "}
          <Link to="/">Open a book and save the media you want first.</Link>
        </p>
      )}
      <label>
        Downloader
        <select
          value={downloader?.id || ""}
          onChange={(event) => {
            changed();
            setDownloaderId(event.target.value);
          }}
        >
          <option value="">Choose a tested downloader</option>
          {downloaders.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Library destination
        <select
          value={destination?.id || ""}
          onChange={(event) => {
            changed();
            setDestinationId(event.target.value);
          }}
        >
          <option value="">Choose a verified library route</option>
          {destinations.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {!options.isPending && (!downloaders.length || !destinations.length) && (
        <p className="muted">
          An administrator must test the downloader and verify its
          download-to-library route before a release can be selected.
        </p>
      )}
      {selected && (
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          I checked the release details and it contains{" "}
          {selected.intent.work_title}.
        </label>
      )}
      <button
        className="primary"
        disabled={
          !artifact.current_connection ||
          !selected ||
          !downloader ||
          !destination ||
          !confirmed ||
          save.isPending ||
          options.isFetching ||
          requests.isFetching
        }
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Saving selection…" : "Save release selection"}
      </button>
      {save.isSuccess && (
        <p role="status" className="success">
          Release selection saved. No download has been started.
        </p>
      )}
      {!!history.data?.items.length && (
        <>
          <h3>Saved selections</h3>
          {history.data.items.map((item) => (
            <article key={item.id} className="source-attribution">
              <span>
                <strong>{item.work_title}</strong>
                <small>{item.message}</small>
                {item.state === "prepared" && !item.configuration_current && (
                  <small>
                    Settings changed. Cancel this selection and review the
                    current route.
                  </small>
                )}
              </span>
              {item.dispatch_available && (
                <button
                  className="primary"
                  disabled={startDownload.isPending}
                  onClick={() => startDownload.mutate(item.id)}
                >
                  {startDownload.isPending
                    ? "Queuing download…"
                    : "Start download"}
                </button>
              )}
              {item.state === "committed" && (
                <Link to="/activity">View download</Link>
              )}
              {item.state === "prepared" && (
                <button
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate(item.id)}
                >
                  Cancel selection
                </button>
              )}
            </article>
          ))}
          <div className="button-row">
            {historyOffset > 0 && (
              <button onClick={() => setHistoryOffset((value) => value - 10)}>
                Previous selections
              </button>
            )}
            {historyOffset + 10 < history.data.total && (
              <button onClick={() => setHistoryOffset((value) => value + 10)}>
                More selections
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
