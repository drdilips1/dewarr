import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type OidcSettings = components["schemas"]["OidcSettingsView"];
type PlexSettings = components["schemas"]["PlexSettingsView"];
type PlexServer = components["schemas"]["PlexServerView"];

const PLEX_ERRORS: Record<string, string> = {
  denied: "Plex did not sign you in.",
  mismatch: "That sign-in attempt expired. Try again.",
  rejected: "This Plex account cannot sign in.",
  unavailable: "Plex could not be reached.",
  paused: "Sign-in is paused during recovery review.",
  limited: "Too many sign-in attempts. Try again in ten minutes.",
};

function OidcSettingsPanel() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: ["oidc-settings"],
    queryFn: async () => result(await api.GET("/api/auth/oidc/settings")),
  });
  const [draft, setDraft] = useState<OidcSettings | null>(null);
  const [secret, setSecret] = useState("");
  useEffect(() => {
    if (settings.data) {
      setDraft(settings.data);
      setSecret("");
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) return;
      const { secret_set, redirect_uri, ...fields } = draft;
      void secret_set;
      void redirect_uri;
      return result(
        await api.PUT("/api/auth/oidc/settings", {
          body: { ...fields, client_secret: secret },
        }),
      );
    },
    onSuccess: (saved) => {
      if (!saved) return;
      client.setQueryData(["oidc-settings"], saved);
      setSecret("");
    },
  });
  const discover = useMutation({
    mutationFn: async () => {
      if (!draft?.issuer) throw new Error("Enter the issuer URL first");
      return result(
        await api.POST("/api/auth/oidc/discover", {
          body: { issuer: draft.issuer },
        }),
      );
    },
    onSuccess: (found) =>
      setDraft((current) => (current ? { ...current, ...found } : current)),
  });
  const update = (key: keyof OidcSettings, value: string | boolean) =>
    setDraft((current) =>
      current ? ({ ...current, [key]: value } as OidcSettings) : current,
    );
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Identity provider</h2>
      <p className="muted">
        Sign in with Authentik, Pocket ID, Authelia, or another OpenID Connect
        provider. Local passwords stay available.
      </p>
      {settings.isPending ? (
        <Loading />
      ) : draft ? (
        <>
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => update("enabled", event.target.checked)}
            />
            Enable identity provider sign-in
          </label>
          <div className="form-row">
            <label>
              Button label
              <input
                value={draft.label}
                maxLength={80}
                required
                onChange={(event) => update("label", event.target.value)}
              />
            </label>
            <label>
              Issuer URL
              <input
                value={draft.issuer}
                inputMode="url"
                autoComplete="off"
                onChange={(event) => update("issuer", event.target.value)}
              />
            </label>
          </div>
          <button
            type="button"
            disabled={discover.isPending || !draft.issuer}
            onClick={() => discover.mutate()}
          >
            {discover.isPending ? "Discovering…" : "Discover endpoints"}
          </button>
          <div className="form-row">
            <label>
              Authorize URL
              <input
                value={draft.authorization_endpoint}
                onChange={(event) =>
                  update("authorization_endpoint", event.target.value)
                }
              />
            </label>
            <label>
              Token URL
              <input
                value={draft.token_endpoint}
                onChange={(event) =>
                  update("token_endpoint", event.target.value)
                }
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Userinfo URL
              <input
                value={draft.userinfo_endpoint}
                onChange={(event) =>
                  update("userinfo_endpoint", event.target.value)
                }
              />
            </label>
            <label>
              JWKS URL
              <input
                value={draft.jwks_uri}
                onChange={(event) => update("jwks_uri", event.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Client ID
              <input
                value={draft.client_id}
                autoComplete="off"
                onChange={(event) => update("client_id", event.target.value)}
              />
            </label>
            <label>
              Client secret
              <input
                type="password"
                value={secret}
                autoComplete="new-password"
                placeholder={
                  draft.secret_set
                    ? "Saved — leave blank to keep it"
                    : "From the identity provider"
                }
                onChange={(event) => setSecret(event.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Signing algorithm
              <select
                value={draft.signing_algorithm}
                onChange={(event) =>
                  update("signing_algorithm", event.target.value)
                }
              >
                <option value="RS256">RS256</option>
                <option value="ES256">ES256</option>
              </select>
            </label>
            <label>
              Match existing accounts
              <select
                value={draft.match_existing}
                onChange={(event) =>
                  update("match_existing", event.target.value)
                }
              >
                <option value="off">Do not match</option>
                <option value="username">Username</option>
                <option value="email">Verified email</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              New account access
              <select
                value={draft.default_role}
                onChange={(event) => update("default_role", event.target.value)}
              >
                <option value="member">Member</option>
                <option value="viewer">Viewer</option>
              </select>
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={draft.auto_register}
                onChange={(event) =>
                  update("auto_register", event.target.checked)
                }
              />
              Create accounts on first sign-in
            </label>
          </div>
          <div className="form-row">
            <label>
              Group claim
              <input
                value={draft.group_claim}
                placeholder="groups"
                onChange={(event) => update("group_claim", event.target.value)}
              />
            </label>
            <label>
              Group scope
              <input
                value={draft.group_scope}
                placeholder="Only if the provider requires it"
                onChange={(event) => update("group_scope", event.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Administrator group
              <input
                value={draft.admin_group}
                onChange={(event) => update("admin_group", event.target.value)}
              />
            </label>
            <label>
              Member group
              <input
                value={draft.member_group}
                onChange={(event) => update("member_group", event.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Viewer group
              <input
                value={draft.viewer_group}
                onChange={(event) => update("viewer_group", event.target.value)}
              />
            </label>
          </div>
          <label>
            Redirect URL
            <input
              className="oidc-redirect"
              readOnly
              value={draft.redirect_uri}
            />
          </label>
          <button className="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save identity provider"}
          </button>
        </>
      ) : null}
      <Notice error={settings.error || discover.error || save.error} />
    </form>
  );
}

function PlexSettingsPanel() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: ["plex-settings"],
    queryFn: async () => result(await api.GET("/api/auth/plex/settings")),
  });
  const pending = useQuery({
    queryKey: ["plex-pending"],
    queryFn: async () => result(await api.GET("/api/auth/plex/pending")),
  });
  const [draft, setDraft] = useState<PlexSettings | null>(null);
  const [machineId, setMachineId] = useState("");
  const [plexError] = useState(() => {
    const code = new URLSearchParams(window.location.search).get("plex_error");
    return code ? PLEX_ERRORS[code] : "";
  });
  useEffect(() => {
    if (!plexError) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("plex_error");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, [plexError]);
  useEffect(() => {
    if (!settings.data) return;
    setDraft(settings.data);
    setMachineId((current) => current || settings.data.machine_id);
  }, [settings.data]);
  useEffect(() => {
    const servers = pending.data?.servers ?? [];
    if (!servers.length) return;
    setMachineId((current) =>
      servers.some((server) => server.machine_id === current)
        ? current
        : servers[0].machine_id,
    );
  }, [pending.data]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) return;
      return result(
        await api.PUT("/api/auth/plex/settings", {
          body: {
            enabled: draft.enabled,
            machine_id: machineId,
            auto_register: draft.auto_register,
            default_role: draft.default_role,
          },
        }),
      );
    },
    onSuccess: (saved) => {
      if (!saved) return;
      client.setQueryData(["plex-settings"], saved);
      client.setQueryData(["plex-pending"], { servers: [] });
    },
  });
  const update = (key: keyof PlexSettings, value: string | boolean) =>
    setDraft((current) =>
      current ? ({ ...current, [key]: value } as PlexSettings) : current,
    );
  const servers: PlexServer[] = pending.data?.servers ?? [];
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Plex</h2>
      <p className="muted">
        Let people who can access one Plex server sign in with that account.
        Local passwords stay available.
      </p>
      {settings.isPending ? (
        <Loading />
      ) : draft ? (
        <>
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.enabled}
              disabled={!machineId}
              onChange={(event) => update("enabled", event.target.checked)}
            />
            Enable Plex sign-in
          </label>
          <a className="plex-link" href="/api/auth/plex/link">
            Link a Plex server
          </a>
          {draft.machine_id ? (
            <p className="muted">Linked server: {draft.server_name}</p>
          ) : servers.length ? (
            <p className="muted">
              Choose this server and save to turn on Plex sign-in.
            </p>
          ) : (
            <p className="muted">No Plex server linked yet.</p>
          )}
          {servers.length ? (
            <label>
              Plex server
              <select
                value={machineId}
                onChange={(event) => setMachineId(event.target.value)}
              >
                {servers.map((server) => (
                  <option key={server.machine_id} value={server.machine_id}>
                    {server.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="form-row">
            <label>
              New account access
              <select
                value={draft.default_role}
                onChange={(event) => update("default_role", event.target.value)}
              >
                <option value="member">Member</option>
                <option value="viewer">Viewer</option>
              </select>
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={draft.auto_register}
                onChange={(event) =>
                  update("auto_register", event.target.checked)
                }
              />
              Create accounts on first sign-in
            </label>
          </div>
          <button className="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save Plex sign-in"}
          </button>
        </>
      ) : null}
      <Notice
        error={
          settings.error ||
          pending.error ||
          save.error ||
          (plexError ? new Error(plexError) : null)
        }
      />
    </form>
  );
}

export default function Accounts({ embedded = false }: { embedded?: boolean }) {
  const client = useQueryClient();
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => result(await api.GET("/api/auth/users")),
  });
  const create = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const values = new FormData(form);
      const role = String(values.get("role")) as "admin" | "member" | "viewer";
      const response = result(
        await api.POST("/api/auth/users", {
          body: {
            username: String(values.get("username")),
            display_name: String(values.get("display_name")),
            password: String(values.get("password")),
            role,
          },
        }),
      );
      form.reset();
      return response;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const automation = useMutation({
    mutationFn: async ({ id, allowed }: { id: string; allowed: boolean }) =>
      result(
        await api.PUT("/api/auth/users/{user_id}/automation", {
          params: { path: { user_id: id } },
          body: { allowed: !allowed, expected_allowed: allowed },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["accounts"] }),
  });
  return (
    <>
      <div className="page-heading">
        {!embedded && (
          <div>
            <p className="eyebrow">YOUR HOUSEHOLD</p>
            <h1>Accounts</h1>
            <p className="muted">
              Give each reader their own lists and access.
            </p>
          </div>
        )}
      </div>
      <OidcSettingsPanel />
      <PlexSettingsPanel />
      <form
        className="panel editor"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(e.currentTarget);
        }}
      >
        <h2>Add an account</h2>
        <div className="form-row">
          <label>
            Name
            <input name="display_name" required maxLength={120} />
          </label>
          <label>
            Username
            <input
              name="username"
              autoComplete="off"
              required
              minLength={3}
              maxLength={100}
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            Password
            <input
              name="password"
              type="password"
              required
              minLength={12}
              maxLength={256}
              autoComplete="new-password"
            />
          </label>
          <label>
            Access
            <select name="role" defaultValue="member">
              <option value="member">Member — manage own lists</option>
              <option value="viewer">Viewer — browse only</option>
              <option value="admin">Administrator — manage instance</option>
            </select>
          </label>
        </div>
        <button className="primary" disabled={create.isPending}>
          Create account
        </button>
        <Notice error={create.error} />
      </form>
      <Notice error={accounts.error || automation.error} />
      {accounts.isPending ? (
        <Loading />
      ) : (
        <div className="panel account-list">
          {accounts.data?.map((user) => (
            <div key={user.id}>
              <div>
                <strong>{user.display_name}</strong>
                <p>{user.username}</p>
              </div>
              <span className="status">{user.role}</span>
              {user.role === "member" && (
                <button
                  aria-label={`${user.can_automate ? "Revoke" : "Allow"} list automation for ${user.display_name}`}
                  disabled={automation.isPending}
                  onClick={() =>
                    automation.mutate({
                      id: user.id,
                      allowed: user.can_automate,
                    })
                  }
                >
                  {user.can_automate
                    ? "Disable automation"
                    : "Allow automation"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
