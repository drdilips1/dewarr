import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result, type BookList } from "../api/client";
import { Loading, Notice } from "../components";
import BookDialog from "../components/BookDialog";

export default function ReadingListDetails({
  listId,
  tracked,
  close,
}: {
  listId: string;
  tracked: boolean;
  close: () => void;
}) {
  const list = useQuery({
    queryKey: ["list-settings-details", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}", {
          params: { path: { list_id: listId }, query: { limit: 1 } },
        }),
      ),
  });
  return (
    <BookDialog
      title="List details"
      close={close}
      className="reading-details-dialog"
    >
      <Notice error={list.error} />
      {list.isPending && <Loading />}
      {list.data?.editable && (
        <DetailsForm
          key={`${listId}:${list.data.settings_revision}`}
          list={list.data}
          tracked={tracked}
          close={close}
        />
      )}
      {list.data && !list.data.editable && (
        <p>Only the owner can edit this list.</p>
      )}
    </BookDialog>
  );
}

function DetailsForm({
  list,
  close,
  tracked,
}: {
  list: BookList;
  close: () => void;
  tracked: boolean;
}) {
  const cache = useQueryClient();
  const [name, setName] = useState(list.name);
  const [shared, setShared] = useState(list.shared);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [message, setMessage] = useState("");
  const path = { list_id: list.id };
  const policy = useQuery({
    queryKey: ["list-policy", list.id],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/acquisition", { params: { path } }),
      ),
  });
  async function refresh() {
    await Promise.all(
      [
        "lists",
        "list-settings-details",
        "discovery-personal",
        "reading-subscriptions",
        "list-subscription",
        "list-policy",
      ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
    );
  }
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PATCH("/api/lists/{list_id}", {
          params: { path },
          body: {
            name: name.trim(),
            shared,
            expected_settings_revision: list.settings_revision,
          },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      close();
    },
  });
  const detach = useMutation({
    mutationFn: async () =>
      result(
        await api.DELETE("/api/lists/{list_id}/subscription", {
          params: { path },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      close();
    },
  });
  const pause = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/acquisition/pause", {
          params: { path },
          body: { expected_revision: policy.data!.revision },
        }),
      ),
    onSuccess: async () => {
      setMessage("Automatic downloads paused.");
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async () =>
      result(await api.DELETE("/api/lists/{list_id}", { params: { path } })),
    onSuccess: async () => {
      close();
      await refresh();
    },
  });
  const busy =
    save.isPending || detach.isPending || pause.isPending || remove.isPending;
  return (
    <div className="reading-details-form">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        aria-label="List preferences"
      >
        <label>
          Name
          <input
            value={name}
            maxLength={200}
            required
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={shared}
            onChange={(e) => setShared(e.target.checked)}
          />
          Share with this household
        </label>
        <div className="button-row">
          <button
            className="primary"
            disabled={
              busy ||
              !name.trim() ||
              (name.trim() === list.name && shared === list.shared)
            }
          >
            Save changes
          </button>
        </div>
      </form>
      <Notice
        error={
          save.error ||
          policy.error ||
          detach.error ||
          pause.error ||
          remove.error
        }
      />
      {policy.data?.active &&
        policy.data.configuration.mode === "automatic" && (
          <div className="reading-details-section">
            <p>Automatic downloads are enabled for this list.</p>
            <button disabled={busy} onClick={() => pause.mutate()}>
              Pause automatic downloads
            </button>
          </div>
        )}
      {tracked && (
        <div className="reading-details-section">
          <p className="muted">
            Stop checking the source shelf and keep this list in the app.
          </p>
          <button disabled={busy} onClick={() => detach.mutate()}>
            Stop monitoring
          </button>
        </div>
      )}
      <div className="reading-details-section">
        {confirmRemove ? (
          <>
            <p>
              Remove “{list.name}” from the app? Library files and the original
              reading-account shelf are kept.
            </p>
            <div className="button-row">
              <button disabled={busy} onClick={() => remove.mutate()}>
                Remove list
              </button>
              <button disabled={busy} onClick={() => setConfirmRemove(false)}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <button disabled={busy} onClick={() => setConfirmRemove(true)}>
            Remove this list…
          </button>
        )}
      </div>
      {message && (
        <p role="status" className="muted">
          {message}
        </p>
      )}
    </div>
  );
}
