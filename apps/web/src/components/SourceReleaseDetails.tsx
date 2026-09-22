import { useId, useState } from "react";
import { ReleaseDescription, ReleaseMediaInfo } from "./ReleaseContent";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, ExternalLink } from "lucide-react";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import { transferSize } from "../pages/DownloadConstraints";
import BookDialog from "./BookDialog";

type Item = components["schemas"]["BookSearchView"]["items"][number];
export function ReleaseTags({ release }: { release: Item["release"] }) {
  return (
    <span className="release-tags">
      {release.source === "mam" &&
        (release.freeleech || release.personal_freeleech) && (
          <span className="release-tag freeleech">Freeleech</span>
        )}
      {release.source === "mam" && release.vip && (
        <span className="release-tag vip">VIP</span>
      )}
    </span>
  );
}
export default function SourceReleaseDetails({
  item,
  searchId,
  rank,
  close,
  onInspect,
  disabled,
  canAcquire,
}: {
  item: Item;
  searchId: string;
  rank: number;
  close: () => void;
  onInspect: () => void;
  disabled: boolean;
  canAcquire: boolean;
}) {
  const [tab, setTab] = useState("Description");
  const tabsId = useId();
  const tabs = ["Description", "Media info", "Details"];
  const original = item.release;
  const detail = useQuery({
    queryKey: ["mam-release", original.source_id],
    enabled: original.source === "mam" && item.current_connection,
    queryFn: async () =>
      result(
        await api.GET("/api/sources/mam/releases/{source_id}", {
          params: { path: { source_id: original.source_id } },
        }),
      ),
    staleTime: 60_000,
    retry: false,
  });
  const release = detail.data || original;
  const save = useMutation({
    mutationFn: async () => {
      const artifact = result(
        await api.POST(
          "/api/source-searches/{search_id}/results/{result_id}/artifact",
          { params: { path: { search_id: searchId, result_id: item.id } } },
        ),
      );
      const download = await api.GET(
        "/api/source-artifacts/{artifact_id}/torrent",
        { params: { path: { artifact_id: artifact.id } }, parseAs: "blob" },
      );
      if (!download.response.ok)
        throw new Error("Could not save torrent. Try again.");
      const url = URL.createObjectURL(download.data as Blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `release-${release.source_id}.torrent`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    },
  });
  const mam = release.source === "mam" ? release : null;
  return (
    <BookDialog
      title="Release details"
      close={close}
      className="release-dialog"
    >
      <article className="release-detail">
        <div className="release-detail-title">
          <span className="eyebrow">
            {release.source === "mam" ? "MAM" : release.source} · Rank{" "}
            {rank + 1}
          </span>
          <ReleaseTags release={release} />
        </div>
        <h2>{release.title}</h2>
        <p className="muted">
          {release.authors?.join(", ") || "Author not supplied"}
        </p>
        <div className="release-detail-actions">
          {canAcquire && (
            <>
              <button
                className="primary"
                disabled={disabled || save.isPending}
                onClick={onInspect}
              >
                Inspect this release
              </button>
              <button
                disabled={disabled || save.isPending}
                onClick={() => save.mutate()}
              >
                <Download size={16} />
                {save.isPending ? "Saving…" : "Save torrent"}
              </button>
            </>
          )}
          {mam && (
            <a
              href={`https://www.myanonamouse.net/t/${encodeURIComponent(mam.source_id)}`}
              target="_blank"
              rel="noreferrer"
            >
              View on MAM <ExternalLink size={14} />
            </a>
          )}
        </div>
        <Notice error={save.error} />
        {detail.isFetching && (
          <p className="muted" role="status">
            Loading full source details…
          </p>
        )}
        {detail.error && (
          <p className="notice">
            Could not refresh MAM details. Showing the saved search result.{" "}
            <button onClick={() => detail.refetch()}>Retry details</button>
          </p>
        )}
        {mam && !!mam.tags?.length && (
          <div className="release-tags">
            {mam.tags!.map((tag) => (
              <span className="release-tag" key={tag}>
                {tag}
              </span>
            ))}
          </div>
        )}
        <div
          className="release-tabs"
          role="tablist"
          aria-label="Release information"
        >
          {tabs.map((name, index) => (
            <button
              key={name}
              id={`${tabsId}-tab-${index}`}
              role="tab"
              aria-selected={tab === name}
              aria-controls={`${tabsId}-panel-${index}`}
              tabIndex={tab === name ? 0 : -1}
              onClick={() => setTab(name)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : null;
                if (next !== null) {
                  event.preventDefault();
                  setTab(tabs[next]);
                  document.getElementById(`${tabsId}-tab-${next}`)?.focus();
                }
              }}
            >
              {name}
            </button>
          ))}
        </div>
        <section
          className="release-tab-panel"
          role="tabpanel"
          tabIndex={0}
          id={`${tabsId}-panel-${tabs.indexOf(tab)}`}
          aria-labelledby={`${tabsId}-tab-${tabs.indexOf(tab)}`}
        >
          {tab === "Description" && (
            <ReleaseDescription text={release.description} />
          )}
          {tab === "Media info" && <ReleaseMediaInfo text={mam?.media_info} />}
          {tab === "Details" && (
            <>
              <dl className="release-facts">
                {Object.entries({
                  Format:
                    release.formats?.join(", ").toUpperCase() || "Unknown",
                  Medium:
                    release.medium === "audio"
                      ? "Audiobook"
                      : release.medium === "ebook"
                        ? "Ebook"
                        : "Unknown",
                  Size:
                    release.size_bytes == null
                      ? "Unknown"
                      : transferSize(release.size_bytes),
                  Seeds: release.seeders?.toLocaleString() ?? "Unknown",
                  Narrators: release.narrators?.join(", ") || "Not supplied",
                  Language: release.language || "Not supplied",
                  ...(mam
                    ? {
                        Leechers: mam.leechers?.toLocaleString() ?? "Unknown",
                        "Completed downloads":
                          mam.snatches?.toLocaleString() ?? "Unknown",
                        Uploaded: mam.uploaded_at || "Not supplied",
                        Category: mam.category || "Not supplied",
                        ISBN: mam.isbn || "Not supplied",
                        Series:
                          (mam.series || [])
                            .map(
                              (s) =>
                                `${s.name}${s.position ? ` · ${s.position}` : ""}`,
                            )
                            .join(", ") || "Not supplied",
                      }
                    : {}),
                }).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </section>
        {item.assessment.blocked.map((message) => (
          <p className="notice error" key={message}>
            {message}
          </p>
        ))}
        {!item.current_connection && (
          <p className="notice">
            This result expired or its source changed. Refresh the search.
          </p>
        )}
        {item.assessment.review.map((message) => (
          <p className="notice" key={message}>
            {message}
          </p>
        ))}
      </article>
    </BookDialog>
  );
}
