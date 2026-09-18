import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Notice } from "../components";

export default function AutomaticImportPolicy({
  destinationId,
  revision,
  verified,
  unsaved,
}: {
  destinationId: string;
  revision: string;
  verified: boolean;
  unsaved: boolean;
}) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["automatic-import-policy", destinationId, revision, verified],
    queryFn: async () =>
      result(
        await api.GET(
          "/api/organization/destinations/{destination_id}/automatic-import",
          {
            params: { path: { destination_id: destinationId } },
          },
        ),
      ),
  });
  const save = useMutation({
    mutationFn: async (enabled: boolean) =>
      result(
        await api.PUT(
          "/api/organization/destinations/{destination_id}/automatic-import",
          {
            params: { path: { destination_id: destinationId } },
            body: {
              enabled,
              expected_generation: query.data!.generation,
              destination_revision: revision,
            },
          },
        ),
      ),
    onSettled: () =>
      cache.invalidateQueries({
        queryKey: ["automatic-import-policy", destinationId],
      }),
  });
  return (
    <section aria-label="Automatic import policy" className="library-access">
      <h3>Automatic import</h3>
      <p>
        Import newly completed downloads when one catalog version matches the
        embedded identity and the files pass completeness checks. Uncertain
        books stay for review. Existing completed downloads are not included.
      </p>
      <p className="muted">
        Currently supports EPUB and identified M4B/MP3 recordings. Other
        collection titles, unsupported formats, incomplete track sets and
        ambiguous versions need file review.
      </p>
      <Notice error={query.error || save.error} />
      {query.data && (
        <>
          <p role="status">{query.data.message}</p>
          <div className="button-row">
            {(!query.data.enabled || !query.data.ready) && (
              <button
                disabled={unsaved || save.isPending || !query.data.can_enable}
                onClick={() => save.mutate(true)}
              >
                {query.data.enabled
                  ? "Approve the verified route again"
                  : "Enable automatic import"}
              </button>
            )}
            {query.data.enabled && (
              <button
                disabled={unsaved || save.isPending}
                onClick={() => save.mutate(false)}
              >
                Disable automatic import
              </button>
            )}
          </div>
          {!query.data.can_enable && (
            <p className="muted">
              Save and verify this destination with a conventional layout first.
            </p>
          )}
          {query.data.enabled && (
            <p className="muted">
              Disabling holds automatic work that has not published. Published
              files are preserved. Already started imports remain available for
              explicit file review and recovery.
            </p>
          )}
        </>
      )}
    </section>
  );
}
