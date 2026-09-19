import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Service = components["schemas"]["SetupService"];

function ServiceEvidence({ value }: { value: Service }) {
  return (
    <>
      <strong>{value.name}</strong>{" "}
      <span className="status">
        {value.enabled ? value.status.replaceAll("-", " ") : "Disabled"}
      </span>
      <p className="muted">
        {value.last_success_at
          ? `Last recorded success: ${new Date(value.last_success_at).toLocaleString()}`
          : "No successful operation timestamp recorded."}
      </p>
    </>
  );
}

export default function GettingStarted() {
  const query = useQuery({
    queryKey: ["setup-readiness"],
    queryFn: async () => result(await api.GET("/api/setup/readiness")),
    refetchInterval: 30000,
  });
  const data = query.data;
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">MAKE YOURSELF AT HOME</p>
          <h1>Getting started</h1>
          <p className="muted">
            Bring your library into view, then set up downloads when you are
            ready.
          </p>
        </div>
        <button onClick={() => query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? "Refreshing…" : "Refresh setup status"}
        </button>
      </header>
      <Notice error={query.error} />
      {query.isPending ? <Loading /> : null}
      {query.isError ? (
        <p>Setup status is unavailable. Refresh to check it again.</p>
      ) : data ? (
        <>
          <p className="muted">
            Saved status as of {new Date(data.observed_at).toLocaleString()}.
            This page does not test services or start downloads. Connection
            results describe previous operations; they do not guarantee current
            access.
          </p>
          <h2>Start browsing</h2>
          <div className="connection-grid setup-grid">
            <section className="panel" aria-label="Library setup">
              <p className="eyebrow">1 · YOUR EXISTING BOOKS</p>
              <h3>Connect Audiobookshelf</h3>
              <p>
                Test the connection, then sync its libraries to recognize the
                ebooks and recordings you already own.
              </p>
              {!data.libraries.length ? (
                <p className="notice">No library connection saved.</p>
              ) : (
                data.libraries.map((item) => (
                  <div className="setup-evidence" key={item.id}>
                    <ServiceEvidence value={item} />
                    <p>
                      {item.inventoried_libraries} of {item.libraries}{" "}
                      discovered libraries have an accessible, completed
                      inventory.
                    </p>
                    {!item.enabled ||
                    item.status !== "connected" ||
                    !item.libraries ||
                    item.inventoried_libraries < item.libraries ? (
                      <p>
                        Review the connection and sync before relying on
                        ownership.
                      </p>
                    ) : null}
                  </div>
                ))
              )}
              <Link to="/connections">Set up library connection →</Link>
            </section>
            <section className="panel" aria-label="Catalog setup">
              <p className="eyebrow">2 · FIND YOUR NEXT READ</p>
              <h3>Choose your catalog</h3>
              <p>
                Open Library search needs no account. Connect your personal
                Hardcover account for its catalog, discovery, and supported
                lists.
              </p>
              {data.catalog ? (
                <ServiceEvidence value={data.catalog} />
              ) : (
                <p className="notice">
                  Hardcover is optional and not connected.
                </p>
              )}
              <div className="button-row">
                <Link to="/search">Find a book →</Link>
                <Link to="/metadata">Set up Hardcover →</Link>
              </div>
            </section>
          </div>
          <p>
            You can browse and curate lists before configuring downloads. After
            syncing, check a known ebook and audiobook in{" "}
            <Link to="/library">your library</Link>.
          </p>
          <h2>Prepare downloads</h2>
          <p className="notice">
            {data.download_dispatch_enabled
              ? "Download dispatch is enabled in this installation. Each request still needs eligible sources, a working downloader, and a valid import route."
              : "Download dispatch is disabled in this installation. Browsing and setup are available; new transfers cannot start."}
          </p>
          <div className="connection-grid setup-grid">
            <section className="panel" aria-label="Source setup">
              <p className="eyebrow">3 · AVAILABLE RELEASES</p>
              <h3>Connect download sources</h3>
              <p>
                Start with MAM and the proxy route you use. Add other sources
                whenever you want broader coverage.
              </p>
              {!data.sources.length ? (
                <p>No sources saved.</p>
              ) : (
                data.sources.map((item) => (
                  <div className="setup-evidence" key={item.key}>
                    <ServiceEvidence value={item} />
                    <p>
                      {item.uses_proxy
                        ? "Configured to use a proxy."
                        : "Configured for a direct connection."}
                    </p>
                  </div>
                ))
              )}
              <div className="button-row">
                <Link to="/sources">Set up MAM →</Link>
                <Link to="/sources/audiobookbay">Set up AudiobookBay →</Link>
                <Link to="/sources/prowlarr">Set up Prowlarr →</Link>
              </div>
            </section>
            <section className="panel" aria-label="Downloader setup">
              <p className="eyebrow">4 · DOWNLOAD LOCATION</p>
              <h3>Connect qBittorrent</h3>
              <p>
                Test access and map qBittorrent folders to the download folders
                visible to this app's worker.
              </p>
              {!data.downloaders.length ? (
                <p>No downloader saved.</p>
              ) : (
                data.downloaders.map((item) => (
                  <div className="setup-evidence" key={item.id}>
                    <ServiceEvidence value={item} />
                    <p>
                      {item.mappings_current
                        ? "Saved path mappings match the configured download roots. Filesystem access still needs a real-file check."
                        : "Path mappings need review before downloading."}
                    </p>
                  </div>
                ))
              )}
              {!data.download_roots ? (
                <p className="notice">No worker download roots configured.</p>
              ) : null}
              <Link to="/downloaders">Set up downloader and paths →</Link>
            </section>
            <section className="panel" aria-label="Destination setup">
              <p className="eyebrow">5 · ORGANIZED LIBRARY</p>
              <h3>Choose library destinations</h3>
              <p>
                Choose ebook and audio destinations as needed. Preview naming
                and test the hardlink or copy route using a saved import plan.
              </p>
              {!data.destinations.length ? (
                <p>No destinations saved.</p>
              ) : (
                data.destinations.map((item) => (
                  <div className="setup-evidence" key={item.name}>
                    <strong>
                      {item.name} ·{" "}
                      {item.medium === "audio" ? "Audiobook" : "Ebook"}
                    </strong>
                    <p>
                      {!item.enabled
                        ? "Disabled"
                        : !item.configured
                          ? "Deployment roots need configuration."
                          : item.publication_available
                            ? "A matching route probe is recorded. Import rechecks the selected files and destination."
                            : "A current real-file route check is needed."}
                    </p>
                  </div>
                ))
              )}
              {!data.destination_roots || !data.staging_configured ? (
                <p className="notice">
                  Library roots and a private staging folder must be configured
                  on the worker.
                </p>
              ) : null}
              <div className="button-row">
                <Link to="/organization">Review naming →</Link>
                <Link to="/organization/destinations">
                  Set up destinations →
                </Link>
              </div>
            </section>
          </div>
          <section
            className="panel setup-next"
            aria-label="First download and automation"
          >
            <h2>Try one book, then automate a small list</h2>
            <p>
              Review your format and source preferences. Acquire one book into a
              test library, confirm its files appear correctly in
              Audiobookshelf, and check that the app shows ownership. Repeat the
              request to check for duplicates before enabling a list's automatic
              mode.
            </p>
            {!data.download_dispatch_enabled ? (
              <details>
                <summary>How to enable download dispatch</summary>
                <p>
                  After reviewing the setup above, the operator can set{" "}
                  <code>BOOK_DOWNLOAD_DISPATCH_ENABLED=true</code> for both the
                  API and worker and restart them. This page cannot change that
                  deployment setting. Use a small test list before authorizing a
                  historical backlog.
                </p>
              </details>
            ) : null}
            <div className="button-row">
              <Link to="/download-preferences">
                Review download preferences →
              </Link>
              <Link to="/lists">Curate a reading list →</Link>
              <Link to="/activity">Follow progress →</Link>
            </div>
          </section>
        </>
      ) : null}
    </>
  );
}
