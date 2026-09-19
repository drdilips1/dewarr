import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result, setCsrf } from "../api/client";
import { Loading, Notice } from "../components";

export default function Recovery() {
  const client = useQueryClient();
  const review = useQuery({
    queryKey: ["recovery"],
    queryFn: async () => result(await api.GET("/api/recovery")),
  });
  const logout = useMutation({
    mutationFn: async () => result(await api.POST("/api/auth/logout")),
    onSuccess: () => {
      setCsrf("");
      client.clear();
      window.location.assign("/");
    },
  });
  return (
    <main id="main" className="recovery-page">
      <section
        className="panel recovery-panel"
        aria-labelledby="recovery-title"
      >
        <p className="eyebrow">BOOK SEARCH · OPERATOR REVIEW</p>
        <h1 id="recovery-title">Your restored library is paused</h1>
        <p>
          Downloads, imports and list changes cannot run while recovery review
          is active. Saved library availability must be checked against your
          current media server before automation resumes.
        </p>
        {review.isPending && <Loading />}
        {review.isError && (
          <>
            <Notice error={review.error} />
            <button onClick={() => review.refetch()}>Try again</button>
          </>
        )}
        {review.data && (
          <>
            <h2>Saved workflow evidence</h2>
            <p>
              These counts describe the backup. They do not confirm the current
              state of your downloader or library.
            </p>
            <div className="recovery-counts">
              {[
                { label: "Downloads", counts: review.data.downloads },
                { label: "Imports", counts: review.data.imports },
              ].map(({ label, counts }) => (
                <div key={label}>
                  <h3>{label}</h3>
                  {Object.entries(counts).length ? (
                    <dl>
                      {Object.entries(counts).map(([state, count]) => (
                        <div key={state}>
                          <dt>{state}</dt>
                          <dd>{count}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p>No saved records.</p>
                  )}
                </div>
              ))}
            </div>
            <h2>Before resuming</h2>
            <p>
              Keep the backup, encryption key and publication journals together.
              Preserve the current download, staging and library folders. An
              operator must reconcile remote downloads, published files and
              external list changes with this saved state.
            </p>
            <p className="recovery-limit">
              Automated reconciliation and resume are not available in this
              build. Follow the repository’s recovery runbook; changing the
              recovery environment flag does not clear a restored database.
            </p>
          </>
        )}
        <Notice error={logout.error} />
        <button onClick={() => logout.mutate()} disabled={logout.isPending}>
          Sign out
        </button>
      </section>
    </main>
  );
}
