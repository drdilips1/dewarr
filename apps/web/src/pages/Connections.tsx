import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";

type Connection = components["schemas"]["ConnectionView"];
type Library = components["schemas"]["LibraryView"];

export default function Connections() {
  const cache = useQueryClient();
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [message, setMessage] = useState("");
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: async () => result(await api.GET("/api/integrations")),
    refetchInterval: 10000,
  });
  const libraries = useQuery({
    queryKey: ["libraries"],
    queryFn: async () => result(await api.GET("/api/library/libraries")),
    refetchInterval: 10000,
  });
  const command = useMutation({
    mutationFn: async ({
      connection,
      action,
    }: {
      connection: Connection;
      action: "test" | "sync";
    }) => {
      if (action === "test") {
        const tested = result(
          await api.POST("/api/integrations/{integration_id}/test", {
            params: { path: { integration_id: connection.id } },
          }),
        );
        setMessage(
          tested.last_error ||
            `${connection.name} connected. ${tested.scan_supported ? "Scan access available." : "Inventory access; detection uses the library watcher."}`,
        );
      } else {
        result(
          await api.POST("/api/integrations/{integration_id}/sync", {
            params: {
              path: { integration_id: connection.id },
              header: { "idempotency-key": crypto.randomUUID() },
            },
          }),
        );
        setMessage("Library sync queued. Follow its progress in Activity.");
      }
    },
    onSuccess: () => cache.invalidateQueries(),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CONNECTED LIBRARIES</p>
          <h1>Connections</h1>
          <p className="muted">
            Keep your catalog in sync with Audiobookshelf.
          </p>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          Connect Audiobookshelf
        </button>
      </div>
      <Notice error={connections.error || libraries.error || command.error} />
      {message && (
        <p className="notice" role="status">
          {message} <Link to="/activity">View activity</Link>
        </p>
      )}
      {editing && (
        <ConnectionForm
          key={editing === "new" ? "new" : editing.id}
          connection={editing === "new" ? undefined : editing}
          close={() => setEditing(null)}
        />
      )}
      {connections.isPending ? (
        <Loading />
      ) : connections.data?.length ? (
        <div className="connection-grid">
          {connections.data.map((connection) => (
            <article className="panel" key={connection.id}>
              <div className="section-heading">
                <h2>{connection.name}</h2>
                <span className="status">
                  {connection.enabled
                    ? connection.status.replaceAll("-", " ")
                    : "Disabled"}
                </span>
              </div>
              <p className="muted break-text">{connection.base_url}</p>
              <p>
                {connection.version
                  ? `Audiobookshelf ${connection.version}`
                  : "Version not checked"}
              </p>
              <p className="muted">
                {connection.last_success_at
                  ? `Last inventory: ${new Date(connection.last_success_at).toLocaleString()}`
                  : "No completed inventory sync yet"}
              </p>
              {connection.last_error && (
                <p className="notice error">{connection.last_error}</p>
              )}
              <div className="button-row">
                <button onClick={() => setEditing(connection)}>
                  Edit connection
                </button>
                <button
                  disabled={!connection.enabled || command.isPending}
                  onClick={() => command.mutate({ connection, action: "test" })}
                >
                  Test connection
                </button>
                <button
                  disabled={!connection.enabled || command.isPending}
                  onClick={() => command.mutate({ connection, action: "sync" })}
                >
                  Sync library
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="Bring your library into view">
          Connect Audiobookshelf to see which books and recordings you already
          have.
        </Empty>
      )}
      {!!libraries.data?.length && (
        <section className="library-access">
          <h2>Library access</h2>
          <p className="muted">
            Administrators can browse all connected libraries. Grant other
            readers access below.
          </p>
          {libraries.data.map((library) => (
            <LibraryAccess
              key={library.id + library.granted_user_ids.join(",")}
              library={library}
            />
          ))}
        </section>
      )}
    </>
  );
}

function ConnectionForm({
  connection,
  close,
}: {
  connection?: Connection;
  close: () => void;
}) {
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const fields = new FormData(form);
      const body = {
        kind: "audiobookshelf" as const,
        name: String(fields.get("name")),
        base_url: String(fields.get("base_url")),
        public_url: String(fields.get("public_url")) || null,
        token: String(fields.get("token")) || null,
        enabled: fields.get("enabled") === "on",
      };
      if (connection)
        result(
          await api.PUT("/api/integrations/{integration_id}", {
            params: { path: { integration_id: connection.id } },
            body,
          }),
        );
      else result(await api.POST("/api/integrations", { body }));
      form.reset();
    },
    onSuccess: async () => {
      await cache.invalidateQueries();
      close();
    },
  });
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(event.currentTarget);
      }}
    >
      <h2>
        {connection ? "Edit Audiobookshelf" : "Connect your Audiobookshelf"}
      </h2>
      <Notice error={save.error} />
      <label>
        Connection name
        <input
          name="name"
          defaultValue={connection?.name || "Audiobookshelf"}
          required
          maxLength={120}
        />
      </label>
      <label>
        Server URL
        <input
          name="base_url"
          type="url"
          defaultValue={connection?.base_url}
          placeholder="http://audiobookshelf:80"
          required
          maxLength={2000}
        />
        <small>
          Address reachable from this app's server, including any URL prefix.
        </small>
      </label>
      <label>
        Browser URL (optional)
        <input
          name="public_url"
          type="url"
          defaultValue={connection?.public_url}
          placeholder="https://books.example.com"
          maxLength={2000}
        />
        <small>
          Used for Open in Audiobookshelf links. Defaults to the server URL.
        </small>
      </label>
      <label>
        API token
        <input
          name="token"
          type="password"
          autoComplete="new-password"
          required={!connection}
          maxLength={8192}
          placeholder={
            connection
              ? "Leave blank to keep the saved token"
              : "Paste your Audiobookshelf token"
          }
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          name="enabled"
          defaultChecked={connection?.enabled ?? true}
        />
        Enable connection
      </label>
      {connection && (
        <p className="muted">
          After changing settings, sync again to verify library access.
        </p>
      )}
      <div className="button-row">
        <button className="primary" disabled={save.isPending}>
          Save connection
        </button>
        <button type="button" onClick={close}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function LibraryAccess({ library }: { library: Library }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState(library.granted_user_ids);
  const [saved, setSaved] = useState(false);
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => result(await api.GET("/api/auth/users")),
  });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/library/libraries/{library_id}/grants", {
          params: { path: { library_id: library.id } },
          body: { user_ids: selected },
        }),
      ),
    onSuccess: async () => {
      setSaved(true);
      await cache.invalidateQueries();
    },
  });
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h3>{library.name}</h3>
      <p className="muted">
        {library.accessible ? "Connected" : "Access needs a fresh sync"}
      </p>
      <Notice error={accounts.error || save.error} />
      {accounts.data
        ?.filter((account) => account.role !== "admin")
        .map((account) => (
          <label className="check-label" key={account.id}>
            <input
              type="checkbox"
              checked={selected.includes(account.id)}
              onChange={(event) => {
                setSaved(false);
                setSelected(
                  event.target.checked
                    ? [...selected, account.id]
                    : selected.filter((id) => id !== account.id),
                );
              }}
            />
            {account.display_name}
          </label>
        ))}
      {accounts.data?.some((account) => account.role !== "admin") ? (
        <button disabled={save.isPending}>Save access</button>
      ) : (
        <p>
          <Link to="/accounts">Add a reader account</Link> to grant access.
        </p>
      )}
      {saved && <p role="status">Library access saved.</p>}
    </form>
  );
}
