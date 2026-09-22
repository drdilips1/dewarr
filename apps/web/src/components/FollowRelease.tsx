import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff } from "lucide-react";
import { api, result } from "../api/client";
import { Notice } from "../components";

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

export function basisLabel(basis?: string | null) {
  if (basis === "audiobook") return "Audiobook release";
  if (basis === "work") return "Work date · audiobook date unknown";
  return "Release day unknown";
}

export default function FollowRelease({
  body,
  following = false,
  workId,
  canEdit,
}: {
  body: FollowBody;
  following?: boolean;
  workId?: string | null;
  canEdit: boolean;
}) {
  const cache = useQueryClient();
  const follow = useMutation({
    mutationFn: async () =>
      result(await api.POST("/api/releases/follow", { body })),
    onSuccess: async () => {
      stop.reset();
      await cache.invalidateQueries({ queryKey: ["release-calendar"] });
      await cache.invalidateQueries({ queryKey: ["release-upcoming"] });
      await cache.invalidateQueries({ queryKey: ["series"] });
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
      await cache.invalidateQueries({ queryKey: ["release-calendar"] });
      await cache.invalidateQueries({ queryKey: ["series"] });
    },
  });
  if (!canEdit) return null;
  const watched = following || follow.isSuccess;
  return (
    <div className="release-follow">
      {watched ? (
        <button
          type="button"
          disabled={!workId || stop.isPending}
          onClick={() => stop.mutate()}
        >
          <BellOff size={14} aria-hidden="true" />
          {stop.isPending ? "Stopping…" : "Following"}
        </button>
      ) : (
        <button
          type="button"
          className="primary"
          disabled={follow.isPending}
          onClick={() => follow.mutate()}
        >
          <Bell size={14} aria-hidden="true" />
          {follow.isPending ? "Following…" : "Follow"}
        </button>
      )}
      <Notice error={follow.error || stop.error} />
      {follow.data && !follow.error && (
        <p className="muted" role="status">
          {follow.data.message}
        </p>
      )}
    </div>
  );
}
