import SettingHelp from "../components/SettingHelp";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";
import Order from "./PreferenceOrder";

type Indexer = components["schemas"]["ProwlarrIndexer"];
const standard = {
  mam: "MAM",
  prowlarr: "Prowlarr (fallback)",
  audiobookbay: "AudiobookBay",
};

function unavailable(indexer: Indexer) {
  if (indexer.excluded)
    return indexer.native_mam
      ? "Handled by native MAM or excluded"
      : "Excluded in source settings";
  if (!indexer.enabled) return "Disabled in Prowlarr";
  if (!indexer.supports_search) return "Search unavailable";
  if (indexer.protocol !== "torrent") return "Download protocol unsupported";
  if (
    indexer.categories.length &&
    !indexer.categories.some((value) =>
      [3000, 3030, 7000, 7020].includes(value),
    )
  )
    return "No supported book categories";
  return null;
}

export default function SourcePriorities({
  values,
  onChange,
}: {
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [selected, setSelected] = useState("");
  const indexers = useQuery({
    queryKey: ["prowlarr-indexers"],
    queryFn: async () =>
      result(await api.GET("/api/sources/prowlarr/indexers")),
    enabled: false,
    retry: false,
  });
  const names: Record<string, string> = { ...standard };
  for (const value of values)
    if (value.startsWith("prowlarr:"))
      names[value] = `Prowlarr indexer #${value.slice(9)}`;
  for (const indexer of indexers.data || [])
    names[`prowlarr:${indexer.id}`] =
      `${indexer.name || "Unnamed indexer"} · Prowlarr #${indexer.id}`;
  const chosen = indexers.data?.find(
    (value) => `prowlarr:${value.id}` === selected,
  );
  const canAdd =
    chosen &&
    !unavailable(chosen) &&
    !values.includes(selected) &&
    values.length < 100 &&
    !indexers.isFetching &&
    !indexers.isError;
  return (
    <section aria-label="Source preference editor">
      <Order
        label="Source preference"
        help={
          <SettingHelp label="source priority">
            This order sets download preferences. Source settings control which
            indexers are searched. A Prowlarr fallback entry ranks indexers
            without their own entry. Sources omitted from this list have lowest
            preference.
          </SettingHelp>
        }
        values={values}
        names={names}
        onChange={onChange}
        onRemove={(value) =>
          onChange(values.filter((entry) => entry !== value))
        }
      />
      <div className="button-row">
        {Object.entries(standard)
          .filter(([key]) => !values.includes(key))
          .map(([key, name]) => (
            <button
              key={key}
              type="button"
              disabled={values.length >= 100}
              onClick={() => onChange([...values, key])}
            >
              Add {name}
            </button>
          ))}
      </div>
      <details>
        <summary>Individual Prowlarr priorities</summary>
        <div className="setting-help-row">
          <SettingHelp label="source priority">
            Load your connected indexers, then add the ones you want to rank
            individually. Loading contacts Prowlarr; editing these priorities
            takes effect when you save this form.
          </SettingHelp>
        </div>
        <button
          type="button"
          disabled={indexers.isFetching}
          onClick={() => {
            void indexers.refetch();
          }}
        >
          {indexers.isFetching ? "Loading indexers…" : "Load Prowlarr indexers"}
        </button>
        <Notice error={indexers.error} />
        {indexers.isError && (
          <div className="setting-help-row">
            <SettingHelp label="source priority">
              Current indexers could not be loaded. Saved priorities are
              retained and can still be reordered or removed.
            </SettingHelp>
          </div>
        )}
        {indexers.data && (
          <>
            <div className="setting-help-row">
              <SettingHelp label="source priority">
                Last loaded {new Date(indexers.dataUpdatedAt).toLocaleString()}.
                Reload to check current names and availability.
              </SettingHelp>
            </div>
            <label>
              Indexer to prioritize
              <select
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
                disabled={indexers.isFetching || indexers.isError}
              >
                <option value="">Choose an indexer</option>
                {indexers.data.map((indexer) => {
                  const key = `prowlarr:${indexer.id}`;
                  const reason = values.includes(key)
                    ? "Already prioritized"
                    : unavailable(indexer);
                  return (
                    <option key={key} value={key} disabled={!!reason}>
                      {names[key]}
                      {reason ? ` — ${reason}` : ""}
                    </option>
                  );
                })}
              </select>
            </label>
            <button
              type="button"
              disabled={!canAdd}
              onClick={() => {
                if (!canAdd) return;
                const next = [...values];
                const fallback = next.indexOf("prowlarr");
                next.splice(fallback < 0 ? next.length : fallback, 0, selected);
                onChange(next);
                setSelected("");
              }}
            >
              Add indexer priority
            </button>
            {!indexers.data.length && (
              <p>No indexers were returned by Prowlarr.</p>
            )}
            {values
              .filter((value) => value.startsWith("prowlarr:"))
              .map((value) => {
                const found = indexers.data.find(
                  (indexer) => value === `prowlarr:${indexer.id}`,
                );
                const reason = found
                  ? unavailable(found)
                  : "Not in the last loaded indexer list";
                return reason ? (
                  <p className="muted" key={value}>
                    {names[value]}: {reason}. Its saved priority is retained.
                  </p>
                ) : null;
              })}
          </>
        )}
        {values.length >= 100 && (
          <p className="notice">
            The source preference list has reached its 100-entry limit.
          </p>
        )}
        <Link to="/settings#sources">Configure Prowlarr</Link>
      </details>
    </section>
  );
}
