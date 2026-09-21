import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import DownloadRepair from "./DownloadRepair";

export default function Downloads({ canManage }: { canManage: boolean }) {
  const cache = useQueryClient();
  const downloads = usePagedQuery({
    queryKey: ["downloads"],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/acquisition/downloads", {
          signal,
          params: { query: { offset, limit: 10 } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.pages
        .flatMap((p) => p.items)
        .some(
          (item) =>
            item.state !== "cancelled" &&
            (item.state !== "complete" ||
              item.members.some(
                (member) =>
                  !member.fulfillment && member.target_state === "wanted",
              )),
        )
        ? 3000
        : 15000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
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

  return (
    <section
      id="downloads"
      className="panel library-access requests-panel"
      aria-label="Downloads"
    >
      <h2>Download queue</h2>
      <p className="muted">
        See download progress and whether the requested book is available in
        your library.
      </p>
      <Notice error={downloads.error || action.error} />
      {downloads.isPending && <Loading />}
      {downloads.data && !downloads.error && !downloads.data.items.length && (
        <div className="settings-empty">
          <h3>No downloads yet</h3>
          <p className="muted">
            When a release is selected for a request, its transfer and library
            status will appear here.
          </p>
          <Link to="/requests">View your requests →</Link>
        </div>
      )}
      {downloads.error && (
        <button
          disabled={downloads.isFetching}
          onClick={() => downloads.refetch()}
        >
          Retry download activity
        </button>
      )}
      {!!downloads.data?.items.length && (
        <div className="requests-table-scroll">
          <table
            className="requests-table download-table"
            aria-label="Download queue"
          >
            <thead>
              <tr>
                <th scope="col">Book / release</th>
                <th scope="col">Progress / actions</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {downloads.data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <h3>
                      {item.members.length > 1
                        ? `${item.members.length} books · shared download`
                        : item.work_title}
                    </h3>
                    <p>{item.release_title}</p>
                  </td>
                  <td>
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
                      <div className="download-progress">
                        <progress
                          max={1}
                          value={Math.max(0, Math.min(1, item.progress))}
                          aria-label={`${item.work_title} download progress`}
                        />
                        <span className="muted">
                          {Math.round(item.progress * 100)}% downloaded
                        </span>
                      </div>
                    )}
                    <div className="button-row">
                      {canManage && item.can_cancel && (
                        <button
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate({ id: item.id, cancel: true })
                          }
                        >
                          {item.members.length > 1
                            ? "Cancel entire transfer before submission"
                            : "Cancel before submission"}
                        </button>
                      )}
                      {canManage && item.can_recheck && (
                        <button
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate({ id: item.id, cancel: false })
                          }
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
                  </td>
                  <td>
                    <span className="status">
                      {item.state === "complete" &&
                      item.members.every(
                        (member) => member.fulfillment?.available_now,
                      )
                        ? "Available"
                        : item.state === "complete"
                          ? "Downloaded"
                          : item.state}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <InfiniteScroll query={downloads} />
    </section>
  );
}
