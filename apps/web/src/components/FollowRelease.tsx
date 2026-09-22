import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, ChevronDown } from "lucide-react";
import { Link } from "react-router-dom";
import { api, result, type Auth } from "../api/client";
import { Notice } from "../components";
import { canRequestMedium } from "../permissions";

type FollowBody = {
  work_id?: string | null;
  provider?: "hardcover" | null;
  external_id?: string | null;
  title?: string | null;
  authors?: string[];
  cover_url?: string | null;
  release_date?: string | null;
  basis: "audiobook" | "work" | "unknown";
};

type Mode = "both" | "ebook" | "audio" | "either";

function medium(value: string | null | undefined): Mode | undefined {
  if (
    value === "audio" ||
    value === "ebook" ||
    value === "both" ||
    value === "either"
  )
    return value;
  return undefined;
}

const MEDIA_LABEL = {
  audio: "Audiobook",
  ebook: "Ebook",
  both: "Ebook + audiobook",
  either: "Either format",
} as const;

export function basisLabel(basis?: string | null) {
  if (basis === "audiobook") return "Audiobook release";
  if (basis === "work") return "Work date · audiobook date unknown";
  return "Release day unknown";
}

export function useReleaseWatch(workId?: string | null, enabled = true) {
  return useQuery({
    queryKey: ["release-follow", workId],
    enabled: enabled && !!workId,
    retry: false,
    queryFn: async () =>
      result(
        await api.GET("/api/releases/follow/{work_id}", {
          params: { path: { work_id: workId! } },
        }),
      ),
  });
}

function refreshRelease(cache: ReturnType<typeof useQueryClient>) {
  return Promise.all(
    [
      "release-follow",
      "release-calendar",
      "release-upcoming",
      "series",
      "requests",
      "provider-book",
      "works",
    ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
  );
}

export default function FollowRelease({
  body,
  following = false,
  workId,
  canEdit,
  idleLabel = "Follow",
  activeLabel = "Following",
}: {
  body: FollowBody;
  following?: boolean;
  workId?: string | null;
  canEdit: boolean;
  idleLabel?: string;
  activeLabel?: string;
}) {
  const cache = useQueryClient();
  const menu = useRef<HTMLDetailsElement>(null);
  const { data: session } = useQuery<Auth | null>({
    queryKey: ["session"],
    enabled: false,
  });
  const grants = session?.user.permissions;
  const role = session?.user.role;
  const ebook = canRequestMedium(grants, role, "ebook");
  const audio = canRequestMedium(grants, role, "audio");
  const defaults = useQuery({
    queryKey: ["quick-add-defaults"],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/preferences/{scope}", {
          params: { path: { scope: "personal" } },
        }),
      ),
    enabled: canEdit && !following,
    staleTime: 60_000,
  });
  const preference = defaults.data?.effective.desired_media;
  const saved = medium(preference);
  const follow = useMutation({
    mutationFn: async (mode?: Mode) =>
      result(
        await api.POST("/api/releases/follow", {
          body: mode ? { ...body, mode } : body,
        }),
      ),
    onSuccess: async (value) => {
      stop.reset();
      if (menu.current) menu.current.open = false;
      cache.setQueryData(["release-follow", value.work_id], value);
      await refreshRelease(cache);
    },
  });
  const stop = useMutation({
    mutationFn: async () => {
      if (!workId) return null;
      return result(
        await api.DELETE("/api/releases/follow/{work_id}", {
          params: { path: { work_id: workId } },
        }),
      );
    },
    onSuccess: async (value) => {
      if (!value) return;
      follow.reset();
      cache.removeQueries({ queryKey: ["release-follow", workId] });
      await refreshRelease(cache);
    },
  });
  if (!canEdit) return null;
  const watched = following || follow.isSuccess;
  const mustChoose = defaults.isSuccess && !saved;
  function choose(mode?: Mode) {
    if (menu.current) menu.current.open = false;
    follow.mutate(mode);
  }
  async function request() {
    let media = saved;
    if (!defaults.isSuccess) {
      const fresh = await defaults.refetch();
      media = medium(fresh.data?.effective.desired_media);
    }
    if (!media) {
      if (menu.current) menu.current.open = true;
      return;
    }
    choose(media);
  }
  const pendingLabel = idleLabel === "Follow" ? "Following…" : "Requesting…";
  return (
    <div className="release-follow">
      {watched ? (
        <button
          type="button"
          disabled={!workId || stop.isPending}
          title={
            idleLabel === "Follow"
              ? "Stop following"
              : "Stop this release request"
          }
          onClick={() => stop.mutate()}
        >
          <BellOff size={14} aria-hidden="true" />
          {stop.isPending ? "Stopping…" : activeLabel}
        </button>
      ) : (
        <div className="quick-add-split">
          <button
            type="button"
            className="primary"
            disabled={follow.isPending}
            title={
              mustChoose
                ? "Choose ebook, audiobook, or both. Searching starts on the release day."
                : saved
                  ? `${idleLabel} · ${MEDIA_LABEL[saved]}. Searching starts on the release day.`
                  : idleLabel
            }
            onClick={request}
          >
            <Bell size={14} aria-hidden="true" />
            {follow.isPending ? pendingLabel : idleLabel}
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
            <summary
              aria-label={`${idleLabel} format`}
              title="Choose ebook, audiobook, or both"
            >
              <ChevronDown size={16} />
            </summary>
            <div className="quick-add-options">
              <button
                type="button"
                disabled={follow.isPending || !ebook || !audio}
                onClick={() => choose("both")}
              >
                Both
              </button>
              <button
                type="button"
                disabled={follow.isPending || !ebook}
                onClick={() => choose("ebook")}
              >
                Ebook
              </button>
              <button
                type="button"
                disabled={follow.isPending || !audio}
                onClick={() => choose("audio")}
              >
                Audiobook
              </button>
              <small>Searching starts on the release day.</small>
            </div>
          </details>
        </div>
      )}
      <Notice error={follow.error || stop.error} />
      {follow.data && !follow.error && (
        <p className="muted" role="status">
          {follow.data.message} <Link to="/requests">View requests</Link>
        </p>
      )}
    </div>
  );
}
