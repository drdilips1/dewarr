import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowDown, ArrowUp, Lock, Users, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, result } from "../api/client";
import { BookCard, Empty, Loading, Notice } from "../components";

export default function Lists({ canEdit }: { canEdit: boolean }) {
  const { id } = useParams();
  return id ? (
    <ListDetail id={id} canEdit={canEdit} />
  ) : (
    <ListIndex canEdit={canEdit} />
  );
}

function ListIndex({ canEdit }: { canEdit: boolean }) {
  const client = useQueryClient();
  const lists = useQuery({
    queryKey: ["lists"],
    queryFn: async () => result(await api.GET("/api/lists")),
  });
  const create = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const name = String(new FormData(form).get("name"));
      const created = result(
        await api.POST("/api/lists", { body: { name, shared: false } }),
      );
      form.reset();
      return created;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["lists"] }),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">MAKE ROOM FOR YOUR NEXT READ</p>
          <h1>Your lists</h1>
          <p className="muted">
            Organize a series, a reading challenge, or a little inspiration.
          </p>
        </div>
      </div>
      {canEdit ? (
        <form
          className="panel inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(e.currentTarget);
          }}
        >
          <label className="grow">
            Create a private list
            <input
              name="name"
              placeholder="e.g. Next on the nightstand"
              required
              maxLength={200}
            />
          </label>
          <button className="primary" disabled={create.isPending}>
            Create list
          </button>
        </form>
      ) : null}
      <Notice error={lists.error || create.error} />
      {lists.isPending ? <Loading /> : null}
      {lists.data?.length ? (
        <div className="list-grid">
          {lists.data.map((list) => (
            <Link
              className="list-card panel"
              key={list.id}
              to={`/lists/${list.id}`}
            >
              <div className="list-icon">
                {list.shared ? <Users size={22} /> : <Lock size={22} />}
              </div>
              <h2>{list.name}</h2>
              <p>
                {list.count} {list.count === 1 ? "book" : "books"} ·{" "}
                {list.shared ? "Shared" : "Private"}
              </p>
            </Link>
          ))}
        </div>
      ) : !lists.isPending ? (
        <Empty title="Give your next reads a home">
          Create a list, then add books from their catalog pages.
        </Empty>
      ) : null}
    </>
  );
}

function ListDetail({ id, canEdit }: { id: string; canEdit: boolean }) {
  const client = useQueryClient();
  const path = { list_id: id };
  const list = useQuery({
    queryKey: ["list", id],
    queryFn: async () =>
      result(await api.GET("/api/lists/{list_id}", { params: { path } })),
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["list", id] });
    client.invalidateQueries({ queryKey: ["lists"] });
  };
  const remove = useMutation({
    mutationFn: async (workId: string) =>
      result(
        await api.DELETE("/api/lists/{list_id}/entries/{work_id}", {
          params: { path: { ...path, work_id: workId } },
        }),
      ),
    onSuccess: refresh,
  });
  const share = useMutation({
    mutationFn: async () =>
      result(
        await api.PATCH("/api/lists/{list_id}", {
          params: { path },
          body: {
            name: list.data!.name,
            description: list.data!.description,
            shared: !list.data!.shared,
          },
        }),
      ),
    onSuccess: refresh,
  });
  const reorder = useMutation({
    mutationFn: async ({
      index,
      direction,
    }: {
      index: number;
      direction: number;
    }) => {
      const ids = list.data!.items.map((work) => work.id);
      [ids[index], ids[index + direction]] = [
        ids[index + direction],
        ids[index],
      ];
      return result(
        await api.PUT("/api/lists/{list_id}/order", {
          params: { path },
          body: { work_ids: ids },
        }),
      );
    },
    onSuccess: refresh,
  });
  if (list.isPending) return <Loading />;
  if (!list.data) return <Notice error={list.error} />;
  const editable = canEdit && list.data.editable;
  return (
    <>
      <Link className="back-link" to="/lists">
        <ArrowLeft size={16} />
        All lists
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {list.data.shared ? "SHARED LIST" : "PRIVATE LIST"}
          </p>
          <h1>{list.data.name}</h1>
          <p className="muted">
            {list.data.count} {list.data.count === 1 ? "book" : "books"} ·
            Removing an entry keeps your library files.
          </p>
        </div>
        {editable ? (
          <button onClick={() => share.mutate()} disabled={share.isPending}>
            {list.data.shared ? "Make private" : "Share with this household"}
          </button>
        ) : null}
      </div>
      <Notice error={remove.error || share.error || reorder.error} />
      {list.data.items.length ? (
        <div className="book-grid">
          {list.data.items.map((work, index) => (
            <div key={work.id}>
              <BookCard work={work} />
              {editable ? (
                <div className="card-actions">
                  <button
                    className="icon-button"
                    aria-label={`Move ${work.title} earlier`}
                    disabled={index === 0 || reorder.isPending}
                    onClick={() => reorder.mutate({ index, direction: -1 })}
                  >
                    <ArrowUp size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Move ${work.title} later`}
                    disabled={
                      index === list.data!.items.length - 1 || reorder.isPending
                    }
                    onClick={() => reorder.mutate({ index, direction: 1 })}
                  >
                    <ArrowDown size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Remove ${work.title} from list`}
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(work.id)}
                  >
                    <X size={15} />
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <Empty title="This list is ready for a story">
          Find a title in your catalog and choose Add to list.
        </Empty>
      )}
    </>
  );
}
