import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import PreferenceFields, { EffectivePreferences } from "./PreferenceFields";
type Defaults = components["schemas"]["DefaultsView"];
type Scope = "personal" | "installation";

export default function DownloadPreferences({ admin }: { admin: boolean }) {
  const [saved, setSaved] = useState(false);
  const [scope, setScope] = useState<Scope>("personal");
  const current = useQuery({
    queryKey: ["download-defaults", scope],
    queryFn: async () =>
      result(
        await api.GET("/api/acquisition/preferences/{scope}", {
          params: { path: { scope } },
        }),
      ),
  });
  return (
    <section aria-label="Download defaults">
      <h1>Download defaults</h1>
      <p>
        Set your usual release preferences once. Saved profiles can override
        individual values. Changes apply when you search or activate a list
        again; existing downloads keep their saved settings.
      </p>
      {admin && (
        <label>
          Defaults scope
          <select
            value={scope}
            onChange={(event) => {
              setSaved(false);
              setScope(event.target.value as Scope);
            }}
          >
            <option value="personal">Personal defaults</option>
            <option value="installation">Installation defaults</option>
          </select>
        </label>
      )}
      <Notice error={current.error} />
      {saved && <p role="status">Download defaults saved.</p>}
      {current.isFetching && <Loading />}
      {current.data && !current.isFetching && (
        <Editor
          key={`${scope}:${current.data.revision}`}
          scope={scope}
          current={current.data}
          onSaved={() => setSaved(true)}
          onEdit={() => setSaved(false)}
        />
      )}
    </section>
  );
}

function Editor({
  scope,
  current,
  onSaved,
  onEdit,
}: {
  scope: Scope;
  current: Defaults;
  onSaved: () => void;
  onEdit: () => void;
}) {
  const cache = useQueryClient();
  const [overrides, setOverrides] = useState(current.overrides);
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/acquisition/preferences/{scope}", {
          params: { path: { scope } },
          body: { overrides, expected_revision: current.revision },
        }),
      ),
    onSuccess: async (value) => {
      onSaved();
      cache.setQueryData(["download-defaults", scope], value);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["release-profiles"] }),
        cache.invalidateQueries({ queryKey: ["download-defaults"] }),
      ]);
    },
  });
  return (
    <form
      className="panel editor"
      aria-label="Download default settings"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <PreferenceFields
        overrides={overrides}
        inherited={current.inherited}
        origins={current.inherited_origins}
        onChange={(value) => {
          onEdit();
          setOverrides(value);
        }}
      />
      <EffectivePreferences
        preferences={current.effective}
        origins={current.origins}
      />
      <Notice error={save.error} />
      <div className="button-row">
        <button className="primary" disabled={save.isPending}>
          Save download defaults
        </button>
        <button
          type="button"
          onClick={() => {
            onEdit();
            setOverrides({});
          }}
        >
          Use inherited defaults
        </button>
        <button
          type="button"
          onClick={() =>
            cache.invalidateQueries({ queryKey: ["download-defaults", scope] })
          }
        >
          Reload defaults
        </button>
      </div>
    </form>
  );
}
