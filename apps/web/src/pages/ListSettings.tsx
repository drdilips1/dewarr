import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, result, type BookList } from "../api/client";
import { Notice } from "../components";

export default function ListSettings({
  list,
  onChange,
  onClose,
}: {
  list: BookList;
  onChange: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [name, setName] = useState(list.name);
  const [description, setDescription] = useState(list.description || "");
  const [shared, setShared] = useState(list.shared);
  const [revision] = useState(list.settings_revision);
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PATCH("/api/lists/{list_id}", {
          params: { path: { list_id: list.id } },
          body: {
            name: name.trim(),
            description: description.trim() || null,
            shared,
            expected_settings_revision: revision,
          },
        }),
      ),
    onSuccess: async () => {
      await onChange();
      onClose();
    },
  });
  return (
    <form
      className="panel editor"
      aria-label="Edit list details"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Edit list</h2>
      <label>
        List name
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={200}
        />
      </label>
      <label>
        Description
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={3000}
          rows={3}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={shared}
          onChange={(event) => setShared(event.target.checked)}
        />
        Share with this household
      </label>
      <p className="muted">
        Every signed-in account can read a shared list and its shared book
        metadata. Only you can edit it. Your provider account, acquisition
        settings and library access stay private.
      </p>
      <Notice error={save.error} />
      <div className="button-row">
        <button className="primary" disabled={save.isPending || !name.trim()}>
          Save list details
        </button>
        <button type="button" disabled={save.isPending} onClick={onClose}>
          Cancel editing
        </button>
        {save.error && (
          <button
            type="button"
            onClick={async () => {
              await onChange();
              onClose();
            }}
          >
            Reload list details
          </button>
        )}
      </div>
    </form>
  );
}
