import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Headphones } from "lucide-react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import InfiniteScroll from "../components/InfiniteScroll";
import { usePagedQuery } from "../hooks/usePagedQuery";
import { randomUUID } from "../randomUUID";
import DownloadConstraints from "./DownloadConstraints";
import DownloadRepair from "./DownloadRepair";
import { EffectivePreferences } from "./PreferenceFields";
import {
  nextRequestOffset,
  requestCountLabel,
  type RequestFilter,
} from "./requestFilters";
import { liveDownloadStates, statusLabel } from "./requestStatus";
import { EffectiveScope } from "./ScopeFields";

type Request = components["schemas"]["RequestView"];
type Target = components["schemas"]["TargetView"];

export type { RequestFilter };

const emptyCopy: Record<RequestFilter, string> = {
  all: "No active requests.",
  pending: "No requests are waiting for approval.",
  downloading: "No downloads yet.",
  library: "No requests are in the library yet.",
  declined: "No declined requests.",
  withdrawn: "No withdrawn requests.",
  review: "No downloads need review.",
};

function mediumLabel(slot: string) {
  if (slot === "audio") return "Audiobook";
  if (slot === "either") return "Either";
  return "Ebook";
}

function chipState(label: string, target: Target) {
  if (label === "In library") return "satisfied";
  if (
    label === "Pending" ||
    label === "Importing" ||
    label === "Paused" ||
    label === "Check inventory"
  )
    return "paused";
  if (label === "Declined" || label === "Withdrawn") return "cancelled";
  return target.state;
}

function requester(request: Request) {
  if (request.reasons.some((reason) => reason.label === "Your request"))
    return "You";
  return request.owner_name || "Requested";
}

function shortDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function inProgress(request: Request) {
  return request.targets.some(
    (target) =>
      target.attempt_state && liveDownloadStates.has(target.attempt_state),
  );
}

function expectedStatus(request: Request) {
  if (
    request.approval_status === "approved" ||
    request.approval_status === "declined"
  )
    return request.approval_status;
  return "pending" as const;
}

export default function ActivityRequests({
  canManage,
  status,
  sort,
}: {
  canManage: boolean;
  status: RequestFilter;
  sort: "newest" | "title";
}) {
  const cache = useQueryClient();
  const claimKeys = useRef(new Map<string, string>());
  const requests = usePagedQuery({
    queryKey: ["requests", "board", status, sort],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/requests", {
          signal,
          params: {
            query: {
              offset,
              limit: 10,
              sort,
              ...(status === "all" ? { active_only: true } : { status }),
            },
          },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.items.some(inProgress))
        ? 3000
        : 15000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    initial: 0,
    next: (page, pages, requested) => nextRequestOffset(page, pages, requested),
  });
  const refresh = async () => {
    await Promise.all(
      [
        "requests",
        "request-preview",
        "activity",
        "downloads",
        "list-monitor",
      ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
    );
  };
  const withdraw = useMutation({
    mutationFn: async ({
      intent,
      reason,
    }: {
      intent: string;
      reason: string;
    }) =>
      result(
        await api.DELETE("/api/requests/{intent_id}/reasons/{reason_id}", {
          params: { path: { intent_id: intent, reason_id: reason } },
        }),
      ),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: async ({
      id,
      status: decision,
      download,
      expected,
    }: {
      id: string;
      status: "approved" | "declined";
      download: boolean;
      expected: "pending" | "approved" | "declined";
    }) =>
      result(
        await api.POST("/api/requests/{intent_id}/decision", {
          params: {
            path: { intent_id: id },
            header: { "idempotency-key": randomUUID() },
          },
          body: { status: decision, download, expected_status: expected },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  const transfer = useMutation({
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
    onSuccess: refresh,
  });
  const claim = useMutation({
    mutationFn: async (target: Target) => {
      const revision = `${target.attempt_id}:${target.review_revision}`;
      if (!claimKeys.current.has(revision))
        claimKeys.current.set(revision, randomUUID());
      return result(
        await api.POST("/api/acquisition/reviews/{attempt_id}/claim", {
          params: {
            path: { attempt_id: target.attempt_id! },
            header: { "idempotency-key": claimKeys.current.get(revision)! },
          },
          body: { revision: target.review_revision! },
        }),
      );
    },
    onSettled: refresh,
  });
  return (
    <section className="requests-board" aria-label="Requests">
      <Notice
        error={
          requests.error ||
          withdraw.error ||
          decide.error ||
          transfer.error ||
          claim.error
        }
      />
      {requests.isPending && <Loading />}
      {requests.error && (
        <button
          type="button"
          disabled={requests.isFetching}
          onClick={() => requests.refetch()}
        >
          Retry requests
        </button>
      )}
      {requests.data && (
        <>
          <p className="requests-count muted" role="status">
            {requestCountLabel(
              requests.data.items.length,
              requests.data.total,
              !!requests.data.total_bounded,
              requests.hasNextPage,
            )}
          </p>
          {!requests.data.items.length && !requests.hasNextPage && (
            <p className="requests-empty">{emptyCopy[status]}</p>
          )}
          <div className="request-list">
            {requests.data.items.map((request) => (
              <RequestCard
                key={request.id}
                request={request}
                canManage={canManage}
                busy={
                  withdraw.isPending ||
                  decide.isPending ||
                  transfer.isPending ||
                  claim.isPending
                }
                onWithdraw={(reason) =>
                  withdraw.mutate({ intent: request.id, reason })
                }
                onDecide={(decision, download) =>
                  decide.mutate({
                    id: request.id,
                    status: decision,
                    download,
                    expected: expectedStatus(request),
                  })
                }
                onTransfer={(id, cancel) => transfer.mutate({ id, cancel })}
                onClaim={(target) => claim.mutate(target)}
              />
            ))}
          </div>
          {decide.data?.download_message && (
            <p className="notice" role="status">
              {decide.data.download_message}
            </p>
          )}
          <InfiniteScroll query={requests} />
        </>
      )}
    </section>
  );
}

function RequestCover({ title, url }: { title: string; url?: string | null }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="request-cover" aria-hidden="true">
      {url && !failed ? (
        <img src={url} alt="" onError={() => setFailed(true)} />
      ) : (
        <span>{title}</span>
      )}
    </div>
  );
}

function RequestCard({
  request,
  canManage,
  busy,
  onWithdraw,
  onDecide,
  onTransfer,
  onClaim,
}: {
  request: Request;
  canManage: boolean;
  busy: boolean;
  onWithdraw: (reasonId: string) => void;
  onDecide: (status: "approved" | "declined", download: boolean) => void;
  onTransfer: (attemptId: string, cancel: boolean) => void;
  onClaim: (target: Target) => void;
}) {
  const when = shortDate(request.created_at);
  return (
    <article
      className="request-card"
      aria-label={`${request.work_title} request`}
    >
      <RequestCover title={request.work_title} url={request.cover_url} />
      <div className="request-card-main">
        <h2>
          {request.can_open_book ? (
            <Link to={`/books/${request.work_id}`}>{request.work_title}</Link>
          ) : (
            request.work_title
          )}
        </h2>
        <p className="muted">
          {request.authors?.length
            ? request.authors.join(", ")
            : request.description}
        </p>
        <div className="request-card-targets">
          {request.targets.map((target) => {
            const label = statusLabel(request, target);
            const active =
              !!target.attempt_state &&
              liveDownloadStates.has(target.attempt_state);
            return (
              <div className="request-card-target" key={target.slot}>
                <span
                  className="request-state"
                  data-state={chipState(label, target)}
                >
                  {target.slot === "audio" ? (
                    <Headphones size={12} aria-hidden />
                  ) : (
                    <BookOpen size={12} aria-hidden />
                  )}
                  {mediumLabel(target.slot)} · {label}
                </span>
                {target.message && (
                  <p className="muted request-card-note">{target.message}</p>
                )}
                {target.attempt_message &&
                  target.attempt_message !== target.message && (
                    <p className="muted request-card-note">
                      {target.attempt_message}
                    </p>
                  )}
                {target.repair_message && (
                  <p className="muted request-card-note">
                    {target.repair_message}
                  </p>
                )}
                {target.review_message && (
                  <p className="muted request-card-note">
                    {target.review_message}
                  </p>
                )}
                {target.transfer_notes?.map((note) => (
                  <p className="muted request-card-note" key={note}>
                    {note}
                  </p>
                ))}
                {!!target.shared_books?.length && (
                  <ul
                    className="request-shared-books"
                    aria-label="Other books in this transfer"
                  >
                    {target.shared_books.map((book) => (
                      <li key={book}>{book}</li>
                    ))}
                  </ul>
                )}
                {active && (
                  <div className="download-progress">
                    <progress
                      max={1}
                      {...(typeof target.progress === "number"
                        ? {
                            value: Math.max(0, Math.min(1, target.progress)),
                          }
                        : {})}
                      aria-label={`${request.work_title} download progress`}
                    />
                    {typeof target.progress === "number" && (
                      <span className="muted">
                        {Math.round(target.progress * 100)}% downloaded
                      </span>
                    )}
                  </div>
                )}
                <div className="request-card-actions">
                  {target.next_action === "search" && request.can_open_book && (
                    <Link
                      to={`/books/${request.work_id}?tab=sources&request=${request.id}&slot=${target.slot}`}
                    >
                      Choose release
                    </Link>
                  )}
                  {target.next_action === "selected-release" &&
                    target.source_artifact_id && (
                      <Link
                        to={`/sources/artifacts/${target.source_artifact_id}`}
                      >
                        Release
                      </Link>
                    )}
                  {canManage && target.can_cancel && target.attempt_id && (
                    <button
                      type="button"
                      disabled={busy}
                      aria-label={
                        target.shared_download
                          ? "Cancel for every book"
                          : "Cancel download"
                      }
                      onClick={() => onTransfer(target.attempt_id!, true)}
                    >
                      {target.shared_download
                        ? "Cancel for every book"
                        : "Cancel"}
                    </button>
                  )}
                  {canManage && target.can_recheck && target.attempt_id && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onTransfer(target.attempt_id!, false)}
                    >
                      Recheck
                    </button>
                  )}
                  {target.needs_review &&
                    target.can_claim &&
                    target.attempt_id &&
                    target.review_revision && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onClaim(target)}
                      >
                        {target.review_retry
                          ? "Retry"
                          : target.review_reassignment
                            ? "Reassign"
                            : "Review"}
                      </button>
                    )}
                  {target.inspection_id && (
                    <Link
                      to={`/organization/inspections?inspection=${target.inspection_id}`}
                    >
                      Inspect
                    </Link>
                  )}
                </div>
                {target.can_repair && target.attempt_id && (
                  <DownloadRepair attemptId={target.attempt_id} />
                )}
              </div>
            );
          })}
        </div>
        <RequestDetails request={request} />
      </div>
      <div className="request-card-side">
        <p className="request-card-who">
          <span>{requester(request)}</span>
          {when && <small>{when}</small>}
        </p>
        {(request.can_decide || request.can_start_download) && (
          <div className="request-card-actions">
            {request.can_decide && (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => onDecide("approved", false)}
              >
                Approve
              </button>
            )}
            {request.can_start_download && (
              <button
                type="button"
                className={request.can_decide ? undefined : "primary"}
                disabled={busy}
                onClick={() => onDecide("approved", true)}
              >
                Download
              </button>
            )}
            {request.can_decide && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide("declined", false)}
              >
                Decline
              </button>
            )}
          </div>
        )}
        <div className="request-reasons">
          {request.reasons.map((reason) => (
            <div className="request-reason" key={reason.id}>
              <span className={reason.active ? undefined : "muted"}>
                {reason.label}
                {reason.active ? "" : " · Withdrawn"}
                {reason.approval_status === "pending" &&
                  " · Waiting for approval"}
                {reason.approval_status === "declined" && " · Declined"}
              </span>
              {reason.decision_note && (
                <p className="muted">{reason.decision_note}</p>
              )}
              {request.can_withdraw && reason.active && (
                <button
                  type="button"
                  className="request-withdraw"
                  disabled={busy}
                  aria-label={`Withdraw ${reason.label.toLowerCase()}`}
                  onClick={() => onWithdraw(reason.id)}
                >
                  Withdraw
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function RequestDetails({ request }: { request: Request }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="request-preferences"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Details</summary>
      {open && (
        <div className="request-preferences-body">
          <EffectiveScope
            specification={request.specification}
            origins={request.release_policy?.scope_origins}
          />
          {request.release_policy && (
            <EffectivePreferences
              preferences={request.release_policy.preferences}
              origins={request.release_policy.origins || {}}
            />
          )}
          <DownloadConstraints
            value={request.specification.download_constraints}
          />
        </div>
      )}
    </details>
  );
}
