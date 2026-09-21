import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import PreferenceFields from "./PreferenceFields";
export type Choice = components["schemas"]["PreferenceChoice"];
type Profile = components["schemas"]["ProfileSnapshot"];

export default function RequestPreferences({
  value,
  onChange,
  inherited,
}: {
  value: Choice;
  onChange: (value: Choice) => void;
  inherited?: Profile | null;
}) {
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const selectedId = Object.hasOwn(value, "profile_id")
    ? value.profile_id || ""
    : "inherit";
  const selected =
    selectedId === "inherit"
      ? inherited || profiles.data?.[0]
      : profiles.data?.find((p) => (p.id || "") === selectedId);
  const preferences = selected
    ? { ...selected.preferences, ...(inherited?.list_overrides || {}) }
    : undefined;
  const origins = {
    ...selected?.origins,
    ...Object.fromEntries(
      Object.keys(inherited?.list_overrides || {}).map((field) => [
        field,
        "List override",
      ]),
    ),
  };
  return (
    <details>
      <summary>Download preferences for this request</summary>
      <p className="muted">
        These choices are saved with the request. Independent limits from other
        requests still apply to shared downloads.
      </p>
      <Notice error={profiles.error} />
      {preferences && (
        <PreferenceFields
          includeMedia={false}
          overrides={value.overrides || {}}
          inherited={preferences}
          origins={origins}
          onChange={(overrides) => onChange({ ...value, overrides })}
        />
      )}
    </details>
  );
}
