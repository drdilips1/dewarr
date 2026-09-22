import SettingHelp from "../components/SettingHelp";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Connection = components["schemas"]["SlskdConnectionView"];

export function SlskdConnectionForm({ value }: { value: Connection }) {
  const cache = useQueryClient();
  const [url, setUrl] = useState(value.base_url);
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(value.enabled || !value.configured);
  const refresh = () =>
    cache.invalidateQueries({ queryKey: ["slskd-connection"] });
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/sources/slskd/connection", {
          body: {
            base_url: url,
            api_key: apiKey || null,
            enabled,
            expected_generation: value.generation,
          },
        }),
      ),
    onSuccess: () => {
      setApiKey("");
      refresh();
    },
  });
  const test = useMutation({
    mutationFn: async () =>
      result(await api.POST("/api/sources/slskd/connection/test")),
    onSettled: refresh,
  });
  return (
    <form
      className="panel editor"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <p>
        <SettingHelp label="Soulseek connection">
          slskd is both the search source and the downloader. Soulseek login
          stays in slskd. Dewarr uses a read-write API key, reads the download
          directory, and maps it onto a worker import root.
        </SettingHelp>
      </p>
      <label>
        slskd URL
        <input
          type="url"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="http://127.0.0.1:5030"
          maxLength={2000}
        />
      </label>
      <label>
        API key
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          autoComplete="off"
          placeholder={
            value.has_api_key
              ? "Saved key stays until replaced"
              : "Read-write API key"
          }
          minLength={apiKey ? 16 : undefined}
          maxLength={255}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enabled
      </label>
      <div className="button-row">
        <button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          disabled={test.isPending || !value.configured}
          onClick={() => test.mutate()}
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </button>
      </div>
      <Notice error={save.error || test.error} />
      {value.download_root && (
        <p>
          Download directory: {value.download_root}
          {value.mapped
            ? ". It is mapped to a worker import root."
            : ". Mount this directory on a worker import root, then test again."}
        </p>
      )}
    </form>
  );
}
