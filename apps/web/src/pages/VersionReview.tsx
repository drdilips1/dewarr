import { useMutation, useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import { useRefreshIdentity } from "./IdentityHistory";
import { providerName } from "./ProviderSearch";

type Review = components["schemas"]["VersionReview"];
export default function VersionReviews({ workId }: { workId: string }) {
  const refresh = useRefreshIdentity();
  const reviews = useQuery({
    queryKey: ["version-reviews", workId],
    queryFn: async () =>
      result(
        await api.GET("/api/identity/works/{work_id}/version-reviews", {
          params: { path: { work_id: workId } },
        }),
      ),
  });
  const resolve = useMutation({
    mutationFn: async ({
      review,
      decision,
    }: {
      review: Review;
      decision: "keep" | "separate";
    }) =>
      result(
        await api.POST("/api/identity/versions/{link_id}/review", {
          params: { path: { link_id: review.id } },
          body: { decision, expected_revision: review.revision },
        }),
      ),
    onSuccess: refresh,
  });
  return (
    <>
      <Notice error={reviews.error || resolve.error} />
      {reviews.data?.map((review) => (
        <section
          className="panel editor"
          key={review.id}
          aria-label="Changed edition review"
        >
          <p className="eyebrow">
            {providerName(review.provider)} · EDITION CHANGED
          </p>
          <h3>Review this catalog version</h3>
          <div className="form-row">
            <div>
              <strong>Current version</strong>
              <p>{review.current_title || "Title unknown"}</p>
              <p>
                {review.current_medium} ·{" "}
                {review.current_narrators.join(", ") ||
                  "Narrator not specified"}
              </p>
              <p className="muted">
                {[review.current_language, review.current_publication_year]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p className="muted">
                {review.current_abridged === null
                  ? "Abridgment unknown"
                  : review.current_abridged
                    ? "Abridged"
                    : "Unabridged"}
              </p>
              {Object.entries(review.current_identifiers).map(
                ([key, value]) => (
                  <p className="muted break-text" key={key}>
                    {key}:{" "}
                    {typeof value === "string" ? value : JSON.stringify(value)}
                  </p>
                ),
              )}
            </div>
            <div>
              <strong>Provider now reports</strong>
              <p>{review.proposed.title || "Title unknown"}</p>
              <p>
                {review.proposed.medium} ·{" "}
                {(review.proposed.narrators || []).join(", ") ||
                  "Narrator not specified"}
              </p>
              <p className="muted">
                {[review.proposed.language, review.proposed.publication_year]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p className="muted">
                {review.proposed.abridged == null
                  ? "Abridgment unknown"
                  : review.proposed.abridged
                    ? "Abridged"
                    : "Unabridged"}
              </p>
              {Object.entries(review.proposed.identifiers || {}).map(
                ([key, value]) => (
                  <p className="muted break-text" key={key}>
                    {key}: {value}
                  </p>
                ),
              )}
            </div>
          </div>
          <p className="muted">
            Keep and protect the current metadata, or accept the provider's
            change as a separate version. Existing library copies keep their
            current version.
          </p>
          <div className="button-row">
            <button
              type="button"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ review, decision: "keep" })}
            >
              Keep current version
            </button>
            <button
              type="button"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ review, decision: "separate" })}
            >
              Accept as separate version
            </button>
          </div>
        </section>
      ))}
    </>
  );
}
