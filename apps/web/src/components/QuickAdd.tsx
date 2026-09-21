import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, Download, Headphones } from "lucide-react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";

type Mode = "both" | "ebook" | "audio" | undefined;
export default function QuickAdd({
  workId,
  resolveWork,
  coverFormats,
}: {
  coverFormats?: { ebook: boolean; audio: boolean };
  workId?: string;
  resolveWork?: () => Promise<string>;
}) {
  const cache = useQueryClient();
  const [engaged, setEngaged] = useState(!coverFormats);
  const menu = useRef<HTMLDetailsElement>(null);
  const [resolvedId, setResolvedId] = useState(workId);
  const id = workId || resolvedId;
  const command = useRef({ mode: undefined as Mode, key: crypto.randomUUID() });
  const defaults = useQuery({
    queryKey: ["quick-add-defaults"],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/preferences/{scope}", {
          params: { path: { scope: "personal" } },
        }),
      ),
    enabled: engaged,
    staleTime: coverFormats ? 60_000 : 0,
  });
  const status = useQuery({
    queryKey: ["quick-add", id],
    enabled: !!id && engaged,
    queryFn: async () =>
      result(
        await api.GET("/api/requests/quick-add/latest/{work_id}", {
          params: { path: { work_id: id! } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data &&
      ["queued", "running"].includes(query.state.data.status)
        ? 1500
        : false,
  });
  const add = useMutation({
    mutationFn: async (mode: Mode) => {
      if (command.current.mode !== mode)
        command.current = { mode, key: crypto.randomUUID() };
      const work = id || (await resolveWork!());
      setResolvedId(work);
      const receipt = result(
        await api.POST("/api/requests/quick-add", {
          params: { header: { "idempotency-key": command.current.key } },
          body: { work_id: work, specification: mode ? { mode } : {} },
        }),
      );
      await cache.cancelQueries({ queryKey: ["quick-add", work] });
      cache.setQueryData(["quick-add", work], receipt);
      return receipt;
    },
    onSuccess: () => {
      command.current.key = crypto.randomUUID();
      for (const name of ["requests", "activity", "downloads"])
        void cache.invalidateQueries({ queryKey: [name] });
    },
  });
  const busy =
    add.isPending ||
    !!(status.data && ["queued", "running"].includes(status.data.status));
  const preference = defaults.data?.effective.desired_media;
  const label =
    preference === "audio"
      ? "Audiobook"
      : preference === "ebook"
        ? "Ebook"
        : preference === "both"
          ? "Ebook + audiobook"
          : preference === "either"
            ? "Either format"
            : "Saved preferences";
  function choose(mode: Mode) {
    if (menu.current) menu.current.open = false;
    setEngaged(true);
    add.mutate(mode);
  }
  if (coverFormats)
    return (
      <div
        className={`cover-quick-add ${add.error || status.error || (engaged && status.data) ? "has-feedback" : ""}`}
        onMouseEnter={() => setEngaged(true)}
        onFocus={() => setEngaged(true)}
      >
        <button
          type="button"
          aria-label="Quick add from cover"
          className="primary"
          disabled={busy}
          onClick={() => choose(undefined)}
          title={`Quick add · ${label}`}
        >
          <Download size={16} aria-hidden="true" />
          {busy ? "Adding…" : "Quick add"}
        </button>
        <div className="cover-quick-formats">
          <button
            type="button"
            disabled={busy || coverFormats.ebook}
            aria-label={
              coverFormats.ebook ? "Ebook already in library" : "Download ebook"
            }
            title={
              coverFormats.ebook ? "Ebook already in library" : "Download ebook"
            }
            onClick={() => choose("ebook")}
          >
            <BookOpen size={18} aria-hidden="true" />
          </button>
          <button
            type="button"
            disabled={busy || coverFormats.audio}
            aria-label={
              coverFormats.audio
                ? "Audiobook already in library"
                : "Download audiobook"
            }
            title={
              coverFormats.audio
                ? "Audiobook already in library"
                : "Download audiobook"
            }
            onClick={() => choose("audio")}
          >
            <Headphones size={18} aria-hidden="true" />
          </button>
        </div>
        <Notice error={add.error || status.error} />
        {engaged && status.data && (
          <span className="cover-quick-status" role="status">
            {status.data.message} <Link to="/requests">View downloads</Link>
          </span>
        )}
      </div>
    );
  return (
    <div className="quick-add">
      <div className="quick-add-split">
        <button
          className="primary"
          disabled={busy}
          onClick={() => choose(undefined)}
          title={`Quick add · ${label}. Uses your saved format priorities.`}
        >
          <Download size={16} />
          {busy ? "Adding…" : "Quick add"}
        </button>
        <details
          ref={menu}
          className="quick-add-menu"
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget))
              event.currentTarget.open = false;
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.currentTarget.open = false;
              event.currentTarget.querySelector("summary")?.focus();
            }
          }}
        >
          <summary aria-label="Quick add format" title="Choose a format">
            <ChevronDown size={16} />
          </summary>
          <div className="quick-add-options">
            <button disabled={busy} onClick={() => choose("both")}>
              Both
            </button>
            <button disabled={busy} onClick={() => choose("ebook")}>
              Ebook
            </button>
            <button disabled={busy} onClick={() => choose("audio")}>
              Audiobook
            </button>
            <small>Uses your saved format priorities.</small>
          </div>
        </details>
      </div>
      <Notice error={add.error || status.error} />
      {add.error && (
        <Link to="/settings#preferences">Download preferences</Link>
      )}
      {status.data && (
        <div className="quick-add-status" role="status">
          <span>{status.data.message}</span>{" "}
          <Link to="/requests">View downloads</Link>
          {status.data.status === "held" && id && (
            <>
              {" "}
              · <Link to={`/books/${id}?tab=sources`}>Review sources</Link>
            </>
          )}
        </div>
      )}
    </div>
  );
}
