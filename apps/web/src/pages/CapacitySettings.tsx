import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type View = components["schemas"]["CapacityView"];

export default function CapacitySettings() {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const cache = useQueryClient();
  const settings = useQuery({
    queryKey: ["capacity-settings"],
    queryFn: async () => result(await api.GET("/api/acquisition/capacity")),
    enabled: open,
  });
  return (
    <details
      className="panel editor"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Transfer and storage limits</summary>
      <p>
        Limits apply across this installation. Downloads wait for capacity;
        retries keep their existing transfer identity. Lowering a limit does not
        stop transfers already submitted.
      </p>
      <Notice error={settings.error} />
      {saved && (
        <p role="status">
          Capacity limits saved. Queued work will use these limits at its next
          check.
        </p>
      )}
      {settings.data && (
        <>
          <p>
            {settings.data.occupied_slots} occupied download slots ·{" "}
            {(settings.data.reserved_bytes / 1024 ** 3).toFixed(2)} GiB reserved
            across filesystems
          </p>
          <Editor
            key={settings.data.revision}
            current={settings.data}
            onSaved={(value) => {
              cache.setQueryData(["capacity-settings"], value);
              setSaved(true);
            }}
          />
        </>
      )}
    </details>
  );
}

function Editor({
  current,
  onSaved,
}: {
  current: View;
  onSaved: (value: View) => void;
}) {
  const [limits, setLimits] = useState(current.limits);
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/acquisition/capacity", {
          body: { limits, expected_revision: current.revision },
        }),
      ),
    onSuccess: onSaved,
  });
  return (
    <form
      aria-label="Transfer and storage limits"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Notice error={save.error} />
      <label>
        Active downloads per downloader
        <input
          type="number"
          required
          min={1}
          max={100}
          value={limits.active_transfers}
          onChange={(e) =>
            setLimits({ ...limits, active_transfers: Number(e.target.value) })
          }
        />
      </label>
      <label>
        Automatic transfers per 24 hours
        <input
          type="number"
          required
          min={1}
          max={10000}
          value={limits.automatic_per_day}
          onChange={(e) =>
            setLimits({ ...limits, automatic_per_day: Number(e.target.value) })
          }
        />
      </label>
      <p className="muted">
        The daily budget applies to scheduled automatic dispatch. Explicit
        manual downloads still require a slot and storage capacity.
      </p>
      <label>
        Minimum free storage (GiB)
        <input
          type="number"
          required
          min={0}
          max={1000000}
          step={0.25}
          value={limits.minimum_free_bytes / 1024 ** 3}
          onChange={(e) =>
            setLimits({
              ...limits,
              minimum_free_bytes: Math.round(
                Number(e.target.value) * 1024 ** 3,
              ),
            })
          }
        />
      </label>
      <label>
        Minimum free storage (%)
        <input
          type="number"
          required
          min={0}
          max={50}
          value={limits.minimum_free_percent}
          onChange={(e) =>
            setLimits({
              ...limits,
              minimum_free_percent: Number(e.target.value),
            })
          }
        />
      </label>
      <p className="muted">
        Keep the larger free-space reserve on each filesystem. Hardlinks share
        media bytes; copies reserve extra space. Storage that cannot be measured
        pauses new downloads.
      </p>
      <button className="primary" disabled={save.isPending}>
        {save.isPending ? "Saving capacity limits…" : "Save capacity limits"}
      </button>
    </form>
  );
}
