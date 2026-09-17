import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";

type Preferences = components["schemas"]["MetadataPreferences"];
const fields = [
  "title",
  "authors",
  "description",
  "publication_year",
  "language",
  "cover_url",
];
export const fieldLabel = (field: string) =>
  ({ publication_year: "Publication year", cover_url: "Cover" })[field] ||
  field.charAt(0).toUpperCase() + field.slice(1);

export default function MetadataSettings({ admin }: { admin: boolean }) {
  const client = useQueryClient();
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const account = useQuery({
    queryKey: ["metadata-account"],
    queryFn: async () => result(await api.GET("/api/metadata/account")),
  });
  const preferences = useQuery({
    queryKey: ["metadata-preferences"],
    queryFn: async () => result(await api.GET("/api/metadata/preferences")),
  });
  const save = useMutation({
    mutationFn: async (enabled: boolean) =>
      result(
        await api.PUT("/api/metadata/account", {
          body: { token: token || null, enabled },
        }),
      ),
    onSuccess: (value) => {
      client.setQueryData(["metadata-account"], value);
      setToken("");
      setMessage("Your catalog connection was saved.");
    },
  });
  const test = useMutation({
    mutationFn: async () =>
      result(await api.POST("/api/metadata/account/test")),
    onSuccess: (value) => {
      client.setQueryData(["metadata-account"], value);
      setMessage(
        value.status === "connected"
          ? "Hardcover catalog access verified."
          : "Connection needs attention.",
      );
    },
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR CATALOG</p>
          <h1>Metadata settings</h1>
          <p className="muted">
            Useful defaults, with control where you need it.
          </p>
        </div>
      </div>
      <section className="panel editor">
        <h2>Your Hardcover account</h2>
        <p className="muted">
          This token is private to your account. Open Library search works
          without a token.
        </p>
        <Notice error={account.error || save.error || test.error} />
        {account.isPending && <Loading />}
        {account.data && (
          <>
            <p>
              Connection: <strong>{account.data.status}</strong>
            </p>
            {account.data.last_error && (
              <p className="notice error">{account.data.last_error}</p>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate(true);
              }}
            >
              <label>
                Hardcover API token
                <input
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  required={!account.data.configured}
                  maxLength={8192}
                  placeholder={
                    account.data.configured
                      ? "Leave blank to keep the saved token"
                      : "Enter your token"
                  }
                />
              </label>
              <div className="button-row">
                <button className="primary" disabled={save.isPending}>
                  Save catalog connection
                </button>
                {account.data.configured && (
                  <>
                    <button
                      type="button"
                      onClick={() => test.mutate()}
                      disabled={!account.data.enabled || test.isPending}
                    >
                      {test.isPending ? "Testing…" : "Test catalog connection"}
                    </button>
                    <button
                      type="button"
                      onClick={() => save.mutate(!account.data!.enabled)}
                      disabled={save.isPending}
                    >
                      {account.data.enabled
                        ? "Disable connection"
                        : "Enable connection"}
                    </button>
                  </>
                )}
              </div>
            </form>
          </>
        )}
        {message && (
          <p className="success" role="status">
            {message}
          </p>
        )}
      </section>
      <Notice error={preferences.error} />
      {preferences.data &&
        (admin ? (
          <PreferenceForm value={preferences.data} />
        ) : (
          <p className="muted">
            Catalog defaults are managed by your administrator. Your token and
            lists remain private.
          </p>
        ))}
    </>
  );
}

function PreferenceForm({ value }: { value: Preferences }) {
  const client = useQueryClient();
  const [settings, setSettings] = useState(value);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: async () =>
      result(await api.PUT("/api/metadata/preferences", { body: settings })),
    onSuccess: (result) => {
      client.setQueryData(["metadata-preferences"], result);
      setSaved(true);
    },
  });
  return (
    <form
      className="panel editor"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2>Automatic metadata</h2>
      <p className="muted">
        The primary provider supplies book details. Matched secondary sources
        fill gaps. Protected edits always stay in place.
      </p>
      <div className="form-row">
        <label>
          Primary catalog
          <select
            value={settings.primary}
            onChange={(e) => {
              setSaved(false);
              setSettings({
                ...settings,
                primary: e.target.value as Preferences["primary"],
              });
            }}
          >
            <option value="hardcover">Hardcover</option>
            <option value="openlibrary">Open Library</option>
          </select>
        </label>
        <label>
          Preferred language
          <input
            value={settings.language}
            onChange={(e) =>
              setSettings({ ...settings, language: e.target.value })
            }
            minLength={2}
            maxLength={20}
            required
          />
          <small>
            Editions matching this language code appear first. Their original
            language metadata stays unchanged.
          </small>
        </label>
      </div>
      <details>
        <summary>Advanced provider preferences</summary>
        <label>
          Cover provider
          <select
            value={settings.covers}
            onChange={(e) =>
              setSettings({
                ...settings,
                covers: e.target.value as Preferences["covers"],
              })
            }
          >
            <option value="automatic">Use primary catalog</option>
            <option value="hardcover">Hardcover</option>
            <option value="openlibrary">Open Library</option>
          </select>
        </label>
        <div className="form-row">
          {fields.map((field) => (
            <label key={field}>
              {fieldLabel(field)}
              <select
                value={settings.field_providers?.[field] || ""}
                onChange={(e) => {
                  const next = { ...settings.field_providers };
                  if (e.target.value)
                    next[field] = e.target.value as "hardcover" | "openlibrary";
                  else delete next[field];
                  setSettings({ ...settings, field_providers: next });
                }}
              >
                <option value="">Inherit provider preference</option>
                <option value="hardcover">Hardcover</option>
                <option value="openlibrary">Open Library</option>
              </select>
            </label>
          ))}
        </div>
        <button
          type="button"
          onClick={() =>
            setSettings({
              ...settings,
              covers: "automatic",
              field_providers: {},
            })
          }
        >
          Reset advanced preferences
        </button>
      </details>
      <p className="muted">
        Changes apply on metadata refresh. They do not rename files or start
        downloads.
      </p>
      <Notice error={save.error} />
      <button className="primary" disabled={save.isPending}>
        Save metadata defaults
      </button>
      {saved && (
        <p className="success" role="status">
          Metadata defaults saved.
        </p>
      )}
    </form>
  );
}
