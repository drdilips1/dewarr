import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

export type Profile = components["schemas"]["ProfileSnapshot"];
type Preferences = components["schemas"]["ReleasePreferences"];
const formats = [
  "epub",
  "pdf",
  "mobi",
  "azw",
  "azw3",
  "cbz",
  "cbr",
  "m4b",
  "mp3",
  "flac",
  "aac",
  "ogg",
  "opus",
];

function Order({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <fieldset>
      <legend>{label}</legend>
      <ol className="preference-order">
        {values.map((value, index) => (
          <li key={value}>
            <span>{value}</span>
            <div>
              <button
                type="button"
                aria-label={`Move ${value} up in ${label}`}
                disabled={index === 0}
                onClick={() => {
                  const next = [...values];
                  [next[index - 1], next[index]] = [
                    next[index],
                    next[index - 1],
                  ];
                  onChange(next);
                }}
              >
                ↑
              </button>
              <button
                type="button"
                aria-label={`Move ${value} down in ${label}`}
                disabled={index === values.length - 1}
                onClick={() => {
                  const next = [...values];
                  [next[index + 1], next[index]] = [
                    next[index],
                    next[index + 1],
                  ];
                  onChange(next);
                }}
              >
                ↓
              </button>
            </div>
          </li>
        ))}
      </ol>
    </fieldset>
  );
}

export default function ReleaseProfiles({
  profile,
  onSaved,
}: {
  profile: Profile;
  onSaved: (profile: Profile) => void;
}) {
  const cache = useQueryClient();
  const [name, setName] = useState(profile.id ? profile.name : "My downloads");
  const [preferences, setPreferences] = useState<Preferences>(
    profile.preferences,
  );
  const [limit, setLimit] = useState(
    profile.preferences.maximum_bytes == null
      ? ""
      : String(profile.preferences.maximum_bytes / 1024 ** 3),
  );
  const save = useMutation({
    mutationFn: async (asNew: boolean) => {
      const size = limit === "" ? null : Number(limit) * 1024 ** 3;
      if (size !== null && (!Number.isFinite(size) || size <= 0))
        throw new Error("Enter a positive size limit");
      const body = {
        name,
        preferences: {
          ...preferences,
          maximum_bytes: size == null ? null : Math.round(size),
        },
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
        <p className="muted">
          Identity and supported media come first. Arrange the preferences below
          in the order you want them applied.
        </p>
        <Order
          label="Ranking priorities"
          values={preferences.criteria || ["format", "source", "seeders"]}
          onChange={(values) =>
            setPreferences((p) => ({
              ...p,
              criteria: values as Preferences["criteria"],
            }))
          }
        />
        <Order
          label="Source preference"
          values={preferences.source_order || ["mam", "prowlarr"]}
          onChange={(values) =>
            setPreferences((p) => ({ ...p, source_order: values }))
          }
        />
        <details>
          <summary>Formats and transfer limits</summary>
          <Order
            label="Ebook format preference"
            values={preferences.ebook_formats || []}
            onChange={(values) =>
              setPreferences((p) => ({ ...p, ebook_formats: values }))
            }
          />
          <Order
            label="Audiobook format preference"
            values={preferences.audio_formats || []}
            onChange={(values) =>
              setPreferences((p) => ({ ...p, audio_formats: values }))
            }
          />
          <fieldset>
            <legend>Blocked formats</legend>
            {formats.map((format) => (
              <label className="check-label" key={format}>
                <input
                  type="checkbox"
                  checked={
                    preferences.blocked_formats?.includes(format) || false
                  }
                  onChange={(event) =>
                    setPreferences((p) => ({
                      ...p,
                      blocked_formats: event.target.checked
                        ? [...(p.blocked_formats || []), format]
                        : p.blocked_formats?.filter((f) => f !== format),
                    }))
                  }
                />
                {format.toUpperCase()}
              </label>
            ))}
          </fieldset>
          <label>
            Maximum transfer size (GiB, optional)
            <input
              type="number"
              min="0.01"
              step="any"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
            />
          </label>
          <p className="muted">
            Blocked formats apply to the whole torrent, including companions.
            The inspected torrent is checked again before selection.
          </p>
        </details>
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
  );
}
