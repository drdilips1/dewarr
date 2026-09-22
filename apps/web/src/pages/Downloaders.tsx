import SettingHelp from "../components/SettingHelp";
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";

type Connection = components["schemas"]["DownloaderView"];

export default function Downloaders({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const cache = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const connections = useQuery({
    queryKey: ["downloaders"],
    queryFn: async () => result(await api.GET("/api/downloaders")),
  });
  const test = useMutation({
    mutationFn: async (id: string) =>
      result(
        await api.POST("/api/downloaders/{connection_id}/test", {
          params: { path: { connection_id: id } },
        }),
      ),
    onSettled: () => cache.invalidateQueries({ queryKey: ["downloaders"] }),
  });
  const selected = connections.data?.find(
    (connection) => connection.id === editing,
  );
  return (
    <>
      <header className="page-heading">
        {!embedded && (
          <div>
            <p className="eyebrow">DOWNLOAD CONNECTIONS</p>
            <h1>Downloaders</h1>
            <p>Connect qBittorrent using its Web UI address.</p>
            <Link to="/settings#libraries">Library connections</Link>
          </div>
        )}
        <button className="primary" onClick={() => setEditing("new")}>
          Connect qBittorrent
        </button>
      </header>
      <Notice error={connections.error || test.error} />
      {editing && (editing === "new" || selected) && (
        <ConnectionForm
          key={`${editing}:${selected?.generation || 0}`}
          connection={selected}
          close={() => setEditing(null)}
        />
      )}
      {connections.isPending ? (
        <Loading />
      ) : connections.data?.length ? (
        <div className="connection-grid">
          {connections.data.map((connection) => (
            <article
              className="panel"
              key={connection.id}
              aria-label={connection.name}
            >
              <div className="section-heading">
                <h2>{connection.name}</h2>
                <span className="status">
                  {connection.enabled ? connection.status : "Disabled"}
                </span>
              </div>
              <p className="break-text">{connection.base_url}</p>
              <p>
                {connection.version
                  ? `qBittorrent ${connection.version}`
                  : "Version not checked"}
              </p>
              <p className="muted">
                {connection.last_success_at
                  ? `Last successful test: ${new Date(connection.last_success_at).toLocaleString()}`
                  : "Test the saved connection to check access."}
              </p>
              {connection.last_error && (
                <p className="notice error">{connection.last_error}</p>
              )}
              <dl className="source-facts">
                <dt>Category</dt>
                <dd>{connection.category}</dd>
                {connection.save_path && (
                  <>
                    <dt>qBittorrent folder</dt>
                    <dd className="break-text">{connection.save_path}</dd>
                  </>
                )}
              </dl>
              {connection.mappings_current &&
                connection.mappings.map((mapping) => (
                  <p className="muted break-text" key={mapping.download_root}>
                    {mapping.download_root} → {mapping.worker_path}
                  </p>
                ))}
              <PathMap
                key={`${connection.id}:${connection.generation}`}
                connection={connection}
              />
              <div className="button-row">
                <button onClick={() => setEditing(connection.id)}>
                  Edit downloader
                </button>
                <button
                  disabled={test.isPending || !connection.enabled}
                  onClick={() => test.mutate(connection.id)}
                >
                  {test.isPending && test.variables === connection.id
                    ? "Testing…"
                    : "Test saved connection"}
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : embedded ? (
        <p className="muted">No download clients connected.</p>
      ) : (
        <Empty title="No downloaders connected">
          Add your qBittorrent Web UI address to get started. Credentials are
          optional.
        </Empty>
      )}
    </>
  );
}

function PathMap({ connection }: { connection: Connection }) {
  const cache = useQueryClient();
  const [rows, setRows] = useState(
    connection.mappings.length
      ? connection.mappings.map((item) => ({
          download_root: item.download_root,
          worker_path: item.worker_path,
        }))
      : [{ download_root: connection.save_path, worker_path: "" }],
  );
  const save = useMutation({
    mutationFn: async () => {
      const saved = result(
        await api.PUT("/api/downloaders/{connection_id}", {
          params: { path: { connection_id: connection.id } },
          body: {
            name: connection.name,
            base_url: connection.base_url,
            category: connection.category,
            enabled: connection.enabled,
            expected_generation: connection.generation,
            mappings: rows,
          },
        }),
      );
      return result(
        await api.POST("/api/downloaders/{connection_id}/test", {
          params: { path: { connection_id: saved.id } },
        }),
      );
    },
    onSettled: () => cache.invalidateQueries({ queryKey: ["downloaders"] }),
  });
  if (!connection.save_path) return null;
  return (
    <form
      className="path-map"
      aria-label="Download path mapping"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <fieldset>
        <legend>Download path mapping</legend>
        <p className="muted">
          Map the folder qBittorrent reports to the folder Dewarr can read. Use
          this when the download client and Dewarr see the same files at
          different paths.
        </p>
        {rows.map((row, index) => (
          <div className="path-map-row" key={index}>
            <label>
              Path in qBittorrent
              <input
                value={row.download_root}
                onChange={(event) =>
                  setRows((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index
                        ? { ...item, download_root: event.target.value }
                        : item,
                    ),
                  )
                }
                required
                maxLength={2000}
              />
            </label>
            <label>
              Path on Dewarr
              <input
                value={row.worker_path}
                placeholder="/data/downloads"
                onChange={(event) =>
                  setRows((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index
                        ? { ...item, worker_path: event.target.value }
                        : item,
                    ),
                  )
                }
                required
                maxLength={2000}
              />
            </label>
            {rows.length > 1 && (
              <button
                type="button"
                onClick={() =>
                  setRows((current) =>
                    current.filter((_, itemIndex) => itemIndex !== index),
                  )
                }
              >
                Remove mapping {index + 1}
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          disabled={rows.length >= 20}
          onClick={() =>
            setRows((current) => [
              ...current,
              { download_root: "", worker_path: "" },
            ])
          }
        >
          Add path mapping
        </button>
      </fieldset>
      {!connection.mappings_current && (
        <p className="notice">
          Dewarr cannot read the download folder until this map is saved.
        </p>
      )}
      <Notice error={save.error} />
      <button className="primary" disabled={save.isPending}>
        {save.isPending ? "Saving path map…" : "Save path map"}
      </button>
    </form>
  );
}

function ConnectionForm({
  connection,
  close,
}: {
  connection?: Connection;
  close: () => void;
}) {
  const urlId = useId();
  const cache = useQueryClient();
  const [url, setUrl] = useState(connection?.base_url || "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [category, setCategory] = useState(connection?.category ?? "");
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: connection?.name || "qBittorrent",
        base_url: url,
        username: username || null,
        password: password || null,
        category,
        enabled: connection?.enabled ?? true,
        expected_generation: connection?.generation || 0,
      };
      return connection
        ? result(
            await api.PUT("/api/downloaders/{connection_id}", {
              params: { path: { connection_id: connection.id } },
              body,
            }),
          )
        : result(await api.POST("/api/downloaders", { body }));
    },
    onSuccess: () => {
      setUsername("");
      setPassword("");
      cache.invalidateQueries({ queryKey: ["downloaders"] });
      close();
    },
  });
  return (
    <form
      className="panel editor"
      aria-label="qBittorrent connection settings"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Notice error={save.error} />
      <div style={{ display: "grid", gap: 6, maxWidth: "32rem" }}>
        <div className="setting-label">
          <label htmlFor={urlId} style={{ width: "auto" }}>
            qBittorrent URL or IP address
          </label>
          <SettingHelp label="qBittorrent URL or IP address">
            Use the Web UI address accessible to this app. This connection does
            not change qBittorrent’s VPN or torrent routing.
          </SettingHelp>
        </div>
        <input
          id={urlId}
          type="text"
          placeholder="http://qbittorrent:8080"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
          maxLength={2000}
        />
      </div>
      <label>
        qBittorrent username (optional)
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="off"
          maxLength={300}
        />
      </label>
      <label>
        qBittorrent password (optional)
        <input
          type="password"
          placeholder={connection?.has_credentials ? "••••••••" : undefined}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          maxLength={1000}
        />
      </label>
      {connection && (
        <div className="setting-help-row">
          <SettingHelp label="connection setup">
            Credentials are stored privately. Leave both fields blank to keep
            them. Changing the server address clears saved credentials.
          </SettingHelp>
        </div>
      )}
      <label>
        Download category
        <input
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          pattern="[A-Za-z0-9_-]*"
          maxLength={100}
        />
      </label>
      <p className="muted">
        Set download folders and torrent preferences in qBittorrent.
      </p>
      <div className="button-row">
        <button className="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save downloader"}
        </button>
        <button type="button" onClick={close}>
          Cancel
        </button>
      </div>
    </form>
  );
}
