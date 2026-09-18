import { useEffect, useRef, useState } from "react";
import DownloadConstraints, { transferSize } from "./DownloadConstraints";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Search = components["schemas"]["BookSearchView"];
type Receipt = components["schemas"]["AutomaticSelectionView"];

export default function AutomaticSelection({
  search,
  requestId,
  slot,
}: {
  search: Search;
  requestId: string;
  slot: string;
}) {
  const cache = useQueryClient();
  const [downloaderId, setDownloaderId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const command = useRef({ body: "", key: crypto.randomUUID() });
  const queryKey = ["automatic-selection", requestId, slot];
  const request = useQuery({
    queryKey: ["requests", "selection-linked", requestId],
    queryFn: async () =>
      result(
        await api.GET("/api/requests/{intent_id}", {
          params: { path: { intent_id: requestId } },
        }),
      ),
  });
  const options = useQuery({
    queryKey: ["selection-options"],
    queryFn: async () =>
      result(await api.GET("/api/acquisition/selections/options")),
  });
  const receipt = useQuery({
    queryKey,
    queryFn: async () =>
      result(
        await api.GET(
          "/api/acquisition/automatic-selections/latest/{intent_id}/{slot}",
          {
            params: { path: { intent_id: requestId, slot } },
          },
        ),
      ),
    refetchInterval: (query) =>
      query.state.data &&
      ["queued", "running"].includes(query.state.data.status)
        ? 1500
        : false,
  });
  useEffect(() => {
    if (receipt.data?.status === "completed" && receipt.data.selection_id) {
      for (const key of [
        "requests",
        "downloads",
        "activity",
        "release-selections",
      ])
        void cache.invalidateQueries({ queryKey: [key] });
    }
  }, [
    cache,
    receipt.data?.id,
    receipt.data?.status,
    receipt.data?.selection_id,
  ]);
  const medium =
    slot === "either" ? request.data?.specification.preferred_medium : slot;
  const library =
    request.data?.specification[
      medium === "audio" ? "audio_library_id" : "ebook_library_id"
    ];
  const downloaders = options.data?.downloaders.filter((d) => d.ready) || [];
  const downloader =
    downloaders.find((d) => d.id === downloaderId) ||
    (downloaders.length === 1 ? downloaders[0] : undefined);
  const destinations =
    options.data?.destinations.filter(
      (d) =>
        d.ready &&
        d.medium === medium &&
        d.source_key === downloader?.source_key &&
        (!library || d.library_id === library),
    ) || [];
  const destination =
    destinations.find((d) => d.id === destinationId) ||
    (destinations.length === 1 ? destinations[0] : undefined);
  const saveReceipt = (value: Receipt) => {
    cache.setQueryData(queryKey, value);
    for (const name of ["activity", "requests", "release-selections"])
      void cache.invalidateQueries({ queryKey: [name] });
  };
  const prepare = useMutation({
    mutationFn: async (downloadWhenReady: boolean) => {
      const body = {
        intent_id: requestId,
        slot,
        search_id: search.id,
        downloader_id: downloader!.id,
        downloader_generation: downloader!.generation,
        destination_id: destination!.id,
        destination_revision: destination!.revision,
        download_when_ready: downloadWhenReady,
      };
      const serialized = JSON.stringify(body);
      if (command.current.body !== serialized)
        command.current = { body: serialized, key: crypto.randomUUID() };
      return result(
        await api.POST("/api/acquisition/automatic-selections", {
          params: { header: { "idempotency-key": command.current.key } },
          body,
        }),
      );
    },
    onSuccess: (value) => {
      command.current = { body: "", key: crypto.randomUUID() };
      saveReceipt(value);
    },
  });
  const cancel = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/acquisition/automatic-selections/{operation_id}/cancel",
          {
            params: { path: { operation_id: receipt.data!.id } },
          },
        ),
      ),
    onSuccess: saveReceipt,
  });
  const active =
    !!receipt.data && ["queued", "running"].includes(receipt.data.status);
  const target = request.data?.targets.find((t) => t.slot === slot);
  const fresh =
    search.status === "completed" &&
    !search.stale_identity &&
    Date.parse(search.expires_at) > Date.now();
  const defaultLimit = medium === "ebook" ? 1024 ** 3 : 10 * 1024 ** 3;
  const limit = Math.min(
    search.profile.preferences.maximum_bytes ?? defaultLimit,
    request.data?.specification.download_constraints?.maximum_bytes ??
      defaultLimit,
    defaultLimit,
  );
  const packLimit = Math.min(
    search.profile.preferences.maximum_bytes ?? 50 * 1024 ** 3,
    request.data?.specification.download_constraints?.maximum_bytes ??
      50 * 1024 ** 3,
    50 * 1024 ** 3,
  );
  const unavailable =
    active ||
    prepare.isPending ||
    receipt.isPending ||
    !!receipt.error ||
    !fresh ||
    !downloader ||
    !destination ||
    !!target?.source_artifact_id ||
    target?.state !== "wanted" ||
    request.data?.work_id !== search.work_id;
  const context = new URLSearchParams({
    work: search.work_id,
    request: requestId,
    slot,
  });
  return (
    <section
      className="panel editor"
      aria-label="Automatic release preparation"
    >
      <h3>Prepare the best release</h3>
      <p>
        Use this page’s results and saved profile to inspect up to five
        candidates for your wanted {medium === "ebook" ? "ebook" : "audiobook"}.
        {search.profile.preferences.prefer_series_packs
          ? " Eligible series packs are preferred when catalog and filenames establish coverage. Only this requested book is authorized for import."
          : " Single-book torrents only."}
        Uncertain coverage and exact versions need review.
      </p>
      <p className="muted">
        Single-book transfer limit: {transferSize(limit)}.
        {search.profile.preferences.prefer_series_packs &&
          ` Series pack limit: ${transferSize(packLimit)}, with at most 20 additional known published books.`}{" "}
        Shared requests may impose stricter limits, which are checked before
        selection. Preparing a release does not start a download.
      </p>
      <DownloadConstraints
        value={request.data?.specification.download_constraints}
      />
      <Notice
        error={
          request.error ||
          options.error ||
          receipt.error ||
          prepare.error ||
          cancel.error
        }
      />
      <label>
        Preparation downloader
        <select
          value={downloader?.id || ""}
          disabled={active || prepare.isPending}
          onChange={(e) => {
            setDownloaderId(e.target.value);
            setDestinationId("");
          }}
        >
          <option value="">Choose a verified downloader</option>
          {downloaders.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Preparation library destination
        <select
          value={destination?.id || ""}
          disabled={active || prepare.isPending}
          onChange={(e) => setDestinationId(e.target.value)}
        >
          <option value="">Choose a verified destination</option>
          {destinations.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      {!options.isPending && (!downloaders.length || !destinations.length) && (
        <p>
          Verify a matching downloader and library destination in Settings and
          Organization first.
        </p>
      )}
      {!fresh && <p>Refresh source results before preparing a release.</p>}
      <button
        className="primary"
        disabled={unavailable}
        onClick={() => prepare.mutate(false)}
      >
        {prepare.isPending || active
          ? "Preparing eligible release…"
          : "Prepare best eligible release"}
      </button>
      <button
        className="secondary"
        disabled={unavailable || !destination?.automatic_import_ready}
        onClick={() => prepare.mutate(true)}
      >
        Select and download automatically
      </button>
      <p className="muted">
        Automatic acquisition starts one eligible download after selection and
        continues through the approved import route. It uses the shared transfer
        and storage limits. EPUB, M4B and MP3 can continue without file review
        when their downloaded contents match the catalog.
        {!destination?.automatic_import_ready &&
          " An administrator must enable dispatch and approve automatic importing for this destination first."}
      </p>
      {receipt.data && (
        <div aria-live="polite">
          <p role="status">{receipt.data.message}</p>
          <p>
            {receipt.data.inspections} of {receipt.data.maximum_inspections}{" "}
            candidates inspected · {receipt.data.status}
          </p>
          <p className="muted">
            {receipt.data.selection_id
              ? "Transfer limit for this selection: "
              : "Single-book transfer limit: "}
            {transferSize(receipt.data.maximum_bytes)}
            {!receipt.data.selection_id &&
              receipt.data.maximum_pack_bytes &&
              ` · Eligible series pack limit: ${transferSize(receipt.data.maximum_pack_bytes)}`}
          </p>
          {(active ||
            (receipt.data.selection_id &&
              !receipt.data.download_id &&
              ["held", "failed"].includes(receipt.data.status))) && (
            <button disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel release preparation
            </button>
          )}
          <div className="button-row">
            {receipt.data.artifact_id && (
              <Link
                to={`/sources/artifacts/${receipt.data.artifact_id}?${context}`}
              >
                Open prepared release
              </Link>
            )}
            {receipt.data.download_id && (
              <Link to="/activity">View automatic download</Link>
            )}
          </div>
          {!!receipt.data.decisions.length && (
            <details>
              <summary>
                Candidate decisions ({receipt.data.decisions.length})
              </summary>
              <ul>
                {receipt.data.decisions.map((d) => (
                  <li key={d.result_id}>
                    <strong>{d.title}</strong> · {d.source}:{" "}
                    {d.reasons.length
                      ? d.reasons.join("; ")
                      : d.inspected
                        ? d.selected
                          ? "Eligible torrent prepared"
                          : "Eligible inspected candidate"
                        : "Not inspected"}
                    {d.coverage && (
                      <details>
                        <summary>
                          {d.coverage.series_name} · {d.coverage.members.length}{" "}
                          catalog-matched books
                        </summary>
                        <p>
                          Filenames corroborate coverage. Actual contents and
                          library availability are checked after download.
                        </p>
                        <ul>
                          {d.coverage.members.map((member) => (
                            <li key={member.work.id}>
                              {member.work.title}
                              {member.work.id === d.coverage?.target_id
                                ? " · Requested"
                                : " · Not requested"}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
