import SettingHelp from "../components/SettingHelp";
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
    <section
      aria-label="Automatic import policy"
      className="automatic-import-setting"
    >
      <div className="setting-subheading">
        <h3>Import on completion</h3>
        <SettingHelp label="automatic import">
          Applies to new downloads after enabling. EPUB and identified M4B/MP3
          recordings import when identity and completeness checks pass.
          Ambiguous books, unsupported formats and incomplete tracks stay for
          review. Disabling holds unpublished automatic work and preserves
          published files.
        </SettingHelp>
      </div>
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
        </>
      )}
    </section>
  );
}
