import { connectionLabel } from "./settingLabels";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import { MamConnectionForm } from "./Sources";
import { AudiobookBayConnectionForm } from "./AudiobookBaySources";
import { ProwlarrConnectionForm } from "./ProwlarrSources";

export default function SourceSettings() {
  const cache = useQueryClient();
  const mam = useQuery({
    queryKey: ["mam-connection"],
    queryFn: async () => result(await api.GET("/api/sources/mam/connection")),
  });
  const abb = useQuery({
    queryKey: ["abb-connection"],
    queryFn: async () =>
      result(await api.GET("/api/sources/audiobookbay/connection")),
  });
  const prowlarr = useQuery({
    queryKey: ["prowlarr-connection"],
    queryFn: async () =>
      result(await api.GET("/api/sources/prowlarr/connection")),
  });
  return (
    <div className="source-settings">
      <section aria-label="MAM settings">
        <details
          className="source-connection"
          open={mam.data?.configured || undefined}
        >
          <summary>
            <span>MAM</span>
            <span className="connection-state">
              {connectionLabel(mam.data?.status)}
            </span>
          </summary>
          <Notice error={mam.error} />
          {mam.isPending && <Loading />}
          {mam.data && (
            <MamConnectionForm key={mam.data.generation} value={mam.data} />
          )}
        </details>
      </section>
      <section aria-label="Prowlarr settings">
        <details
          className="source-connection"
          open={prowlarr.data?.configured || undefined}
        >
          <summary>
            <span>Prowlarr</span>
            <span className="connection-state">
              {connectionLabel(prowlarr.data?.status)}
            </span>
          </summary>
          <Notice error={prowlarr.error} />
          {prowlarr.isPending && <Loading />}
          {prowlarr.data && (
            <ProwlarrConnectionForm
              key={prowlarr.data.generation}
              connection={prowlarr.data}
              onSaved={() => {
                cache.invalidateQueries({ queryKey: ["prowlarr-connection"] });
                cache.invalidateQueries({ queryKey: ["prowlarr-indexers"] });
              }}
            />
          )}
        </details>
      </section>
      <section aria-label="AudiobookBay settings">
        <details
          className="source-connection"
          open={abb.data?.configured || undefined}
        >
          <summary>
            <span>AudiobookBay</span>
            <span className="connection-state">
              {connectionLabel(abb.data?.status)}
            </span>
          </summary>
          <Notice error={abb.error} />
          {abb.isPending && <Loading />}
          {abb.data && (
            <AudiobookBayConnectionForm
              key={abb.data.generation}
              value={abb.data}
            />
          )}
        </details>
      </section>
    </div>
  );
}
