import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";
import DownloadRepair from "./DownloadRepair";

export default function Downloads({ canManage }: { canManage: boolean }) {
  const [offset, setOffset] = useState(0);
  const cache = useQueryClient();
  const downloads = useQuery({
    queryKey: ["downloads", offset],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/downloads", {
          params: { query: { offset, limit: 10 } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (item) =>
          item.state !== "cancelled" &&
          (item.state !== "complete" ||
            item.members.some(
              (member) =>
                !member.fulfillment && member.target_state === "wanted",
            )),
      )
        ? 3000
        : false,
  });
  const action = useMutation({
    mutationFn: async ({ id, cancel }: { id: string; cancel: boolean }) => {
      const params = { path: { attempt_id: id } };
      return result(
        cancel
          ? await api.DELETE("/api/acquisition/downloads/{attempt_id}", {
              params,
            })
          : await api.POST("/api/acquisition/downloads/{attempt_id}/recheck", {
              params,
            }),
      );
    },
    onSuccess: async () => {
      await Promise.all(
        ["downloads", "activity", "requests", "release-selections"].map((key) =>
          cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
  if (!downloads.data?.items.length && !downloads.error) return null;
  return (
    <section className="panel library-access" aria-label="Downloads">
      <h2>Downloads</h2>
      <p className="muted">
        See download progress and whether the requested book is available in
        your library.
      </p>
      <Notice error={downloads.error || action.error} />
      {downloads.data?.items.map((item) => (
        <article className="activity-row" key={item.id}>
          <div className="grow">
            <h3>
              {item.members.length > 1
                ? `${item.members.length} books · shared download`
                : item.work_title}
            </h3>
            <p>{item.release_title}</p>
            <p>{item.message}</p>
            {item.repair && <p>{item.repair.message}</p>}
            {item.members.length > 1 && (
              <ul aria-label="Books in this download">
                {item.members.map((member) => (
                  <li key={member.selection_id}>
                    <strong>{member.work_title}</strong> ·{" "}
                    {member.medium === "audio" ? "Audiobook" : "Ebook"}
                    {member.join_operation_id && (
                      <span className="muted">
                        {" "}
                        · Uses this existing download
                      </span>
                    )}
                    <p>
                      {member.fulfillment?.available_now
                        ? "Confirmed in your library"
                        : member.message}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            {(item.import_continuations ?? []).map((continuation) => (
              <p key={continuation.id}>
                <strong>
                  {continuation.state === "held" ||
                  continuation.state === "attention"
                    ? "Additional books need attention: "
                    : "Additional books: "}
                </strong>
                {continuation.message}
              </p>
            ))}
            {item.members.length === 1 && item.fulfillment && (
              <p>
                {item.fulfillment.available_now
                  ? item.fulfillment.basis === "imported"
                    ? "Imported and confirmed in your library."
                    : "Request satisfied by a book already available in your library."
                  : "Previously fulfilled; current library availability needs attention."}
              </p>
            )}
            {item.progress !== null && item.progress !== undefined && (
              <p className="muted">
                {Math.round(item.progress * 100)}% downloaded
              </p>
            )}
            <div className="button-row">
              {canManage && item.can_cancel && (
                <button
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: item.id, cancel: true })}
                >
                  {item.members.length > 1
                    ? "Cancel entire transfer before submission"
                    : "Cancel before submission"}
                </button>
              )}
              {canManage && item.can_recheck && (
                <button
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: item.id, cancel: false })}
                >
                  {item.state === "complete"
                    ? (item.import_continuations ?? []).some(
                        (continuation) => continuation.state === "held",
                      )
                      ? "Recheck saved files"
                      : "Check library availability"
                    : "Check existing transfer"}
                </button>
              )}
              {item.inspection_id && (
                <Link
                  to={`/organization/inspections?inspection=${item.inspection_id}`}
                >
                  Review downloaded files
                </Link>
              )}
            </div>
            {item.can_repair && <DownloadRepair attemptId={item.id} />}
          </div>
          <span className="status">
            {item.state === "complete" &&
            item.members.every((member) => member.fulfillment?.available_now)
              ? "Available"
              : item.state === "complete"
                ? "Downloaded"
                : item.state}
          </span>
        </article>
      ))}
      <div className="button-row">
        {offset > 0 && (
          <button onClick={() => setOffset((value) => value - 10)}>
            Previous downloads
          </button>
        )}
        {downloads.data && offset + 10 < downloads.data.total && (
          <button onClick={() => setOffset((value) => value + 10)}>
            More downloads
          </button>
        )}
      </div>
    </section>
  );
}
