import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clock } from "lucide-react";
import { api, result } from "../api/client";
import Downloads from "./Downloads";
import DownloadReviews from "./DownloadReviews";
import { Empty, Loading, Notice } from "../components";

export default function Activity({
  admin,
  canRequest,
}: {
  admin: boolean;
  canRequest: boolean;
}) {
  const client = useQueryClient();
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: async () => result(await api.GET("/api/activity")),
    refetchInterval: (query) =>
      query.state.data?.some((item) =>
        ["queued", "running"].includes(item.status),
      )
        ? 2000
        : false,
  });
  useEffect(() => {
    if (
      activity.data?.some(
        (item) => item.kind === "library.sync" && item.status === "completed",
      )
    ) {
      for (const key of [
        "assets",
        "catalog",
        "work",
        "works",
        "requests",
        "request-preview",
        "libraries",
        "connections",
      ]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
    }
  }, [activity.data, client]);
  const probe = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/system/probe", {
          params: { header: { "idempotency-key": crypto.randomUUID() } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["activity"] }),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">EVERY STEP, IN VIEW</p>
          <h1>Activity</h1>
          <p className="muted">
            Track requests and see what needs your attention.
          </p>
        </div>
        {admin ? (
          <button onClick={() => probe.mutate()} disabled={probe.isPending}>
            Check background worker
          </button>
        ) : null}
      </div>
      <Downloads canManage={canRequest} />
      {admin && <DownloadReviews />}
      <Notice error={activity.error || probe.error} />
      {activity.isPending ? <Loading /> : null}
      {activity.data?.length ? (
        <div className="activity-list">
          {activity.data.map((item) => (
            <article className="activity-row" key={item.id}>
              <div
                className={
                  item.status === "completed"
                    ? "activity-icon success"
                    : "activity-icon"
                }
              >
                {item.status === "completed" ? (
                  <Check size={20} />
                ) : (
                  <Clock size={20} />
                )}
              </div>
              <div className="grow">
                <h2>
                  {item.kind === "lists.sync"
                    ? "Goodreads shelf observation"
                    : item.kind === "sources.search"
                      ? "Book source search"
                      : item.kind === "system.probe"
                        ? "Background worker check"
                        : item.kind === "organization.automatic"
                          ? "Automatic library import"
                          : item.kind === "library.sync"
                            ? "Audiobookshelf inventory sync"
                            : item.kind === "acquisition.evaluate"
                              ? "Wanted media check"
                              : item.kind === "acquisition.download"
                                ? "Book download"
                                : item.kind === "acquisition.repair"
                                  ? "Download connection repair"
                                  : item.kind === "acquisition.review"
                                    ? "Download import review"
                                    : item.kind === "acquisition.select"
                                      ? "Release selection"
                                      : item.kind === "metadata.enrich" ||
                                          item.kind ===
                                            "metadata.resolve-import"
                                        ? "Automatic metadata lookup"
                                        : item.kind}
                </h2>
                <p>{item.message}</p>
              </div>
              <div className="activity-meta">
                <span className="status">{item.status}</span>
                <time dateTime={item.created_at}>
                  {new Date(item.created_at).toLocaleString()}
                </time>
              </div>
            </article>
          ))}
        </div>
      ) : !activity.isPending ? (
        <Empty title="Nothing in the queue">
          Your requests and background checks will appear here.
        </Empty>
      ) : null}
    </>
  );
}
