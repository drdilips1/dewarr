import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";
import CapacitySettings from "./CapacitySettings";

type Connection = components["schemas"]["DownloaderView"];
type Mapping = components["schemas"]["DownloadMapping"];

export default function Downloaders() {
  const cache = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const connections = useQuery({
    queryKey: ["downloaders"],
    queryFn: async () => result(await api.GET("/api/downloaders")),
  });
  const roots = useQuery({
    queryKey: ["download-roots"],
    queryFn: async () =>
      result(await api.GET("/api/organization/download-roots")),
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
        <div>
          <p className="eyebrow">DOWNLOAD CONNECTIONS</p>
          <h1>Downloaders</h1>
          <p>
            Connect qBittorrent and map its download folders to your worker.
          </p>
          <Link to="/connections">Library connections</Link>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          Connect qBittorrent
        </button>
      </header>
      <p className="notice">
        Downloads require an enabled acquisition workflow and verified library
        destinations.
      </p>
      <Notice error={connections.error || roots.error || test.error} />
      <CapacitySettings />
      {editing && roots.data && (editing === "new" || selected) && (
        <ConnectionForm
          key={`${editing}:${selected?.generation || 0}`}
          connection={selected}
          roots={roots.data}
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
              {!connection.mappings_current && (
                <p className="notice error">
                  Worker download roots changed. Review and save the path
                  mappings.
                </p>
              )}
              <dl className="source-facts">
                <dt>Save folder</dt>
                <dd className="break-text">{connection.save_path}</dd>
                <dt>Category</dt>
                <dd>{connection.category}</dd>
              </dl>
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
              <PathPreview
                key={connection.generation}
                connection={connection}
              />
            </article>
          ))}
        </div>
      ) : (
        <Empty title="No downloaders connected">
          Add your qBittorrent Web UI address and credentials to get started.
        </Empty>
      )}
    </>
  );
}

function ConnectionForm({
  connection,
  roots,
  close,
}: {
  connection?: Connection;
  roots: string[];
  close: () => void;
}) {
  const cache = useQueryClient();
  const [name, setName] = useState(connection?.name || "qBittorrent");
  const [url, setUrl] = useState(connection?.base_url || "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [savePath, setSavePath] = useState(
    connection?.save_path || "/downloads/books",
  );
  const [category, setCategory] = useState(
    connection?.category || "book-search",
  );
  const [enabled, setEnabled] = useState(connection?.enabled ?? true);
  const [mappings, setMappings] = useState<Mapping[]>(
    connection?.mappings.map(({ download_root, source_key }) => ({
      download_root,
      source_key,
    })) || [{ download_root: "/downloads", source_key: roots[0] || "" }],
  );
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name,
        base_url: url,
        username: username || null,
        password: password || null,
        save_path: savePath,
        category,
        mappings,
        enabled,
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
  function mapping(index: number, change: Partial<Mapping>) {
    setMappings((items) =>
      items.map((item, position) =>
        position === index ? { ...item, ...change } : item,
      ),
    );
  }
  return (
    <form
      className="panel editor"
      aria-label="qBittorrent connection settings"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>{connection ? "Edit qBittorrent" : "Connect qBittorrent"}</h2>
      <Notice error={save.error} />
      <label>
        Connection name
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={120}
        />
      </label>
      <label>
        qBittorrent URL
        <input
          type="url"
          placeholder="http://qbittorrent:8080"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
          maxLength={2000}
        />
      </label>
      <p className="muted">
        Use the Web UI address accessible to this app. This connection does not
        change qBittorrent’s VPN or torrent routing.
      </p>
      <label>
        qBittorrent username
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="off"
          required={!connection || Boolean(password)}
          maxLength={300}
        />
      </label>
      <label>
        qBittorrent password
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          required={!connection || Boolean(username)}
          maxLength={1000}
        />
      </label>
      {connection && (
        <p className="muted">
          Credentials are stored privately. Leave both fields blank to keep
          them; enter both again when changing the server address.
        </p>
      )}
      <label>
        Download save folder
        <input
          value={savePath}
          onChange={(event) => setSavePath(event.target.value)}
          required
          maxLength={2000}
        />
      </label>
      <p className="muted">
        Enter the folder as qBittorrent sees it. Library destinations and
        hardlink settings are configured in{" "}
        <Link to="/organization/destinations">Organization</Link>.
      </p>
      <fieldset>
        <legend>Download path mappings</legend>
        <p className="muted">
          Match each qBittorrent folder to the same storage mounted on the
          worker.
        </p>
        {!roots.length && (
          <p className="notice error">
            No worker download roots are configured. Configure the worker’s
            download mounts before saving this connection.
          </p>
        )}
        {mappings.map((item, index) => (
          <fieldset key={index}>
            <legend>Mapping {index + 1}</legend>
            <label>
              qBittorrent root folder
              <input
                value={item.download_root}
                onChange={(event) =>
                  mapping(index, { download_root: event.target.value })
                }
                required
                maxLength={2000}
              />
            </label>
            <label>
              Worker download root
              <select
                value={item.source_key}
                onChange={(event) =>
                  mapping(index, { source_key: event.target.value })
                }
                required
              >
                <option value="">Select a root</option>
                {!roots.includes(item.source_key) && item.source_key && (
                  <option value={item.source_key}>
                    {item.source_key} (unavailable)
                  </option>
                )}
                {roots.map((root) => (
                  <option key={root} value={root}>
                    {root}
                  </option>
                ))}
              </select>
            </label>
            {mappings.length > 1 && (
              <button
                type="button"
                onClick={() =>
                  setMappings((items) =>
                    items.filter((_, position) => position !== index),
                  )
                }
              >
                Remove mapping {index + 1}
              </button>
            )}
          </fieldset>
        ))}
        <button
          type="button"
          disabled={mappings.length >= 20}
          onClick={() =>
            setMappings((items) => [
              ...items,
              { download_root: "", source_key: roots[0] || "" },
            ])
          }
        >
          Add path mapping
        </button>
      </fieldset>
      <details>
        <summary>Advanced</summary>
        <label>
          Download category
          <input
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            required
            pattern="[A-Za-z0-9_-]+"
            maxLength={100}
          />
        </label>
      </details>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable connection
      </label>
      <div className="button-row">
        <button className="primary" disabled={save.isPending || !roots.length}>
          {save.isPending ? "Saving…" : "Save downloader"}
        </button>
        <button type="button" onClick={close}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function PathPreview({ connection }: { connection: Connection }) {
  const [path, setPath] = useState(connection.save_path);
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/downloaders/{connection_id}/preview-path", {
          params: { path: { connection_id: connection.id } },
          body: { path, expected_generation: connection.generation },
        }),
      ),
  });
  return (
    <details>
      <summary>Preview path mapping</summary>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          preview.mutate();
        }}
      >
        <label>
          Path in qBittorrent
          <input
            value={path}
            onChange={(event) => {
              setPath(event.target.value);
              preview.reset();
            }}
            required
            maxLength={2000}
          />
        </label>
        <button disabled={preview.isPending || !connection.mappings_current}>
          {preview.isPending ? "Previewing…" : "Preview saved mapping"}
        </button>
      </form>
      <Notice error={preview.error} />
      {preview.data && (
        <div role="status">
          <p className="break-text">Worker path: {preview.data.worker_path}</p>
          <p className="break-text">
            Download root: {preview.data.source_key} · Relative path:{" "}
            {preview.data.relative_path || "root folder"}
          </p>
          <p className="muted">
            Mapping preview only. File access and hardlink support are checked
            during import setup.
          </p>
        </div>
      )}
    </details>
  );
}
