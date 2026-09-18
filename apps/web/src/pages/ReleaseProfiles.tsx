import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import PreferenceFields, { EffectivePreferences } from "./PreferenceFields";
export type Profile = components["schemas"]["ProfileSnapshot"];

export default function ReleaseProfiles({
  profile,
  defaults,
  onSaved,
}: {
  profile: Profile;
  defaults: Profile;
  onSaved: (profile: Profile) => void;
}) {
  const cache = useQueryClient();
  const [name, setName] = useState(profile.id ? profile.name : "My downloads");
  const [overrides, setOverrides] = useState(profile.overrides || {});
  const save = useMutation({
    mutationFn: async (asNew: boolean) => {
      const body = {
        name,
        preferences: overrides,
        expected_generation: asNew ? 0 : profile.generation,
      };
      return asNew || !profile.id
        ? result(await api.POST("/api/acquisition/profiles", { body }))
        : result(
            await api.PUT("/api/acquisition/profiles/{profile_id}", {
              params: { path: { profile_id: profile.id } },
              body,
            }),
          );
    },
    onSuccess: async (saved) => {
      await cache.invalidateQueries({ queryKey: ["release-profiles"] });
      onSaved(saved);
    },
  });
  return (
    <>
      <EffectivePreferences
        preferences={profile.preferences}
        origins={profile.origins || {}}
      />
      <Link to="/download-preferences">
        Personal and installation download defaults
      </Link>
      <details>
        <summary>Customize download preferences</summary>
        <form
          className="panel editor"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(!profile.id);
          }}
        >
          <label>
            Profile name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={100}
            />
          </label>
          <PreferenceFields
            overrides={overrides}
            inherited={defaults.preferences}
            origins={defaults.origins || {}}
            onChange={setOverrides}
          />
          <Notice error={save.error} />
          <div className="button-row">
            <button className="primary" disabled={save.isPending}>
              {profile.id ? "Save profile" : "Create profile"}
            </button>
            {profile.id && (
              <button
                type="button"
                disabled={save.isPending}
                onClick={() => save.mutate(true)}
              >
                Save as new profile
              </button>
            )}
          </div>
        </form>
      </details>
    </>
  );
}
