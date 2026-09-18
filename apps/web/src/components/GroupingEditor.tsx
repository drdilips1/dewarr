import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Notice } from "../components";

type Inspection = components["schemas"]["InspectionView"];
type Grouping = components["schemas"]["GroupingView"];
type Assignment = {
  group: string;
  disc: number | null;
  track: number | null;
  reason: string;
};

export default function GroupingEditor({
  inspection,
  grouping,
  onSave,
  onCancel,
}: {
  inspection: Inspection;
  grouping: Grouping;
  onSave: (value: Grouping) => void;
  onCancel: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [assignments, setAssignments] = useState<Record<string, Assignment>>(
    () => {
      const rows: Record<string, Assignment> = {};
      for (const group of grouping.content.groups)
        for (const file of group.files)
          rows[file.path] = {
            group: group.key,
            disc: file.disc ?? null,
            track: file.track ?? null,
            reason: "",
          };
      for (const file of grouping.content.excluded)
        rows[file.path] = {
          group: "",
          disc: null,
          track: null,
          reason: file.reason,
        };
      return rows;
    },
  );
  const groupIds = [
    ...new Set(
      Object.values(assignments)
        .map((row) => row.group)
        .filter(Boolean),
    ),
  ];
  const labels = new Map(
    grouping.content.groups.map((group) => [
      group.key,
      group.title || "Unidentified book",
    ]),
  );
  const save = useMutation({
    mutationFn: async (reset: boolean) => {
      const groups = groupIds.map((group) => ({
        files: Object.entries(assignments)
          .filter(([, row]) => row.group === group)
          .map(([path, row]) => ({ path, disc: row.disc, track: row.track })),
      }));
      const excluded = Object.entries(assignments)
        .filter(([, row]) => !row.group)
        .map(([path, row]) => ({ path, reason: row.reason.trim() }));
      return result(
        await api.PUT(
          "/api/organization/inspections/{inspection_id}/grouping",
          {
            params: { path: { inspection_id: inspection.id } },
            body: {
              inspection_revision: inspection.snapshot!.revision,
              expected_revision: grouping.revision,
              action: reset ? "reset" : "replace",
              groups: reset ? [] : groups,
              excluded: reset ? [] : excluded,
            },
          },
        ),
      );
    },
    onSuccess: onSave,
  });
  const change = (path: string, update: Partial<Assignment>) =>
    setAssignments((current) => ({
      ...current,
      [path]: { ...current[path], ...update },
    }));
  return (
    <section
      className="panel editor group-editor"
      aria-label="Edit file groups"
    >
      <h3>Review file groups</h3>
      <p className="muted">
        Each group becomes one book version. Move files to join groups, or
        choose New group to separate a book. Excluded files stay in the
        download. Source files are never changed.
      </p>
      <p>
        {groupIds.length} book groups ·{" "}
        {Object.values(assignments).filter((row) => !row.group).length} excluded
        files
      </p>
      {inspection.snapshot!.files.slice(offset, offset + 25).map((file) => {
        const row = assignments[file.path];
        return (
          <fieldset
            className="library-access group-file"
            key={file.path}
            disabled={save.isPending}
          >
            <legend className="import-path">{file.path}</legend>
            {file.reason && <p className="muted">{file.reason}</p>}
            <label>
              Book group for {file.path}
              <select
                value={row.group}
                disabled={file.state !== "inspected"}
                onChange={(event) => {
                  const group =
                    event.target.value === "__new__"
                      ? crypto.randomUUID()
                      : event.target.value;
                  change(file.path, {
                    group,
                    reason: group
                      ? ""
                      : row.reason || "Excluded during collection review",
                  });
                }}
              >
                <option value="">Exclude from import</option>
                {groupIds.map((id, index) => (
                  <option key={id} value={id}>
                    Group {index + 1} · {labels.get(id) || "Reviewed book"}
                  </option>
                ))}
                <option value="__new__">New group</option>
              </select>
            </label>
            {!row.group ? (
              <label>
                Exclusion reason for {file.path}
                <input
                  value={row.reason}
                  maxLength={300}
                  onChange={(event) =>
                    change(file.path, { reason: event.target.value })
                  }
                />
              </label>
            ) : (
              file.medium === "audio" && (
                <div className="actions">
                  <label>
                    Disc for {file.path}
                    <input
                      type="number"
                      min={1}
                      max={999}
                      value={row.disc ?? ""}
                      onChange={(event) =>
                        change(file.path, {
                          disc: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    />
                  </label>
                  <label>
                    Track for {file.path}
                    <input
                      type="number"
                      min={1}
                      max={999999}
                      value={row.track ?? ""}
                      onChange={(event) =>
                        change(file.path, {
                          track: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    />
                  </label>
                </div>
              )
            )}
          </fieldset>
        );
      })}
      <div className="actions">
        <button
          disabled={!offset || save.isPending}
          onClick={() => setOffset((value) => Math.max(0, value - 25))}
        >
          Previous files
        </button>
        <button
          disabled={
            offset + 25 >= inspection.snapshot!.files.length || save.isPending
          }
          onClick={() => setOffset((value) => value + 25)}
        >
          More files
        </button>
      </div>
      <Notice error={save.error} />
      <div className="actions">
        <button
          className="primary"
          disabled={save.isPending}
          onClick={() => save.mutate(false)}
        >
          Save file groups
        </button>
        <button disabled={save.isPending} onClick={() => save.mutate(true)}>
          Restore proposed groups
        </button>
        <button disabled={save.isPending} onClick={onCancel}>
          Cancel group changes
        </button>
      </div>
    </section>
  );
}
