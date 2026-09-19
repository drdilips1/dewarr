import { lazy, Suspense, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Lock, Users } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, result } from "../api/client";
import { Empty, Loading, Notice } from "../components";
import ListCuration from "./ListCuration";
import ListSettings from "./ListSettings";

const ListRequests = lazy(() => import("./ListRequests"));
const ListPolicy = lazy(() => import("./ListPolicy"));

const ListCsv = lazy(() => import("./ListCsv"));

const ListSubscription = lazy(() => import("./ListSubscription"));

export default function Lists({ canEdit }: { canEdit: boolean }) {
  const { id } = useParams();
  return id ? (
    <ListDetail key={id} id={id} canEdit={canEdit} />
  ) : (
    <ListIndex canEdit={canEdit} />
  );
}

function ListIndex({ canEdit }: { canEdit: boolean }) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const lists = useQuery({
    queryKey: ["lists", search, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/page", {
          params: { query: { offset, limit: 25, q: search } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    refetchInterval: 15_000,
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
    onSuccess: () => {
      setOffset(0);
      return client.invalidateQueries({ queryKey: ["lists"] });
    },
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
      <label>
        Find lists
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <Notice error={lists.error || create.error} />
      {lists.isPending ? <Loading /> : null}
      {!lists.error && lists.data?.items.length ? (
        <div className="list-grid">
          {lists.data.items.map((list) => (
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
                {list.shared
                  ? list.editable
                    ? "Shared by you"
                    : "Shared with you"
                  : "Private"}
              </p>
            </Link>
          ))}
        </div>
      ) : !lists.isPending && !lists.error ? (
        <Empty title="No matching lists here">
          Create a list, then add books from their catalog pages.
        </Empty>
      ) : null}
      {!lists.error && lists.data && (offset > 0 || lists.data.total > 25) && (
        <div className="pagination" aria-label="List pages">
          <button disabled={!offset} onClick={() => setOffset(offset - 25)}>
            Previous lists
          </button>
          <span>
            {offset + 1}–{offset + lists.data.items.length} of{" "}
            {lists.data.total}
          </span>
          <button
            disabled={offset + 25 >= lists.data.total}
            onClick={() => setOffset(offset + 25)}
          >
            Next lists
          </button>
        </div>
      )}
    </>
  );
}

function ListDetail({ id, canEdit }: { id: string; canEdit: boolean }) {
  const client = useQueryClient();
  const path = { list_id: id };
  const [offset, setOffset] = useState(0);
  const [pageRevision, setPageRevision] = useState<string>();
  const [search, setSearch] = useState("");
  const [csvOpen, setCsvOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const list = useQuery({
    queryKey: ["list", id, offset, pageRevision, search],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}", {
          params: {
            path,
            query: {
              offset,
              limit: 50,
              expected_revision: pageRevision,
              q: search,
            },
          },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    placeholderData: (previous) => previous,
    refetchInterval: 15_000,
  });
  const refresh = async () => {
    setPageRevision(undefined);
    setOffset(0);
    await Promise.all([
      client.invalidateQueries({ queryKey: ["list", id] }),
      client.invalidateQueries({ queryKey: ["lists"] }),
      client.invalidateQueries({ queryKey: ["works"] }),
      client.invalidateQueries({ queryKey: ["curation-catalog", id] }),
    ]);
  };
  if (list.isPending) return <Loading />;
  if (list.error || !list.data)
    return (
      <>
        <Notice error={list.error} />
        <button
          onClick={() => {
            setPageRevision(undefined);
            setOffset(0);
            void list.refetch();
          }}
        >
          Reload list
        </button>
      </>
    );
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
        {editable && !editing && (
          <button onClick={() => setEditing(true)} aria-expanded={false}>
            Edit list
          </button>
        )}
      </div>
      {list.data.description && (
        <p className="list-description">{list.data.description}</p>
      )}
      {!editable && (
        <p className="muted">
          You have read-only access to this list. Library badges reflect your
          own access.
        </p>
      )}
      <label className="list-search">
        Search this list
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
            setPageRevision(undefined);
          }}
        />
      </label>
      {editable && editing && (
        <ListSettings
          list={list.data}
          onChange={refresh}
          onClose={() => setEditing(false)}
        />
      )}
      {editable ? (
        <div className="list-tools">
          <button
            onClick={() => setRequestsOpen(!requestsOpen)}
            aria-expanded={requestsOpen}
          >
            {requestsOpen ? "Close list requests" : "Request books"}
          </button>
          {requestsOpen && (
            <Suspense fallback={<Loading />}>
              <ListRequests key={id} listId={id} />
            </Suspense>
          )}
          <button
            onClick={() => setPolicyOpen(!policyOpen)}
            aria-expanded={policyOpen}
          >
            {policyOpen ? "Close acquisition policy" : "Acquisition policy"}
          </button>
          {policyOpen && (
            <Suspense fallback={<Loading />}>
              <ListPolicy key={id} listId={id} />
            </Suspense>
          )}
          <button onClick={() => setCsvOpen(!csvOpen)} aria-expanded={csvOpen}>
            {csvOpen ? "Close CSV import" : "Import a CSV"}
          </button>
          {csvOpen ? (
            <Suspense fallback={<Loading />}>
              <ListCsv listId={id} />
            </Suspense>
          ) : null}
        </div>
      ) : null}
      <ListCuration
        list={list.data}
        editable={editable}
        onChange={refresh}
        loading={list.isFetching}
        filtered={Boolean(search.trim())}
        onPage={(next) => {
          setPageRevision(list.data.content_revision);
          setOffset(next);
        }}
      />
      {editable && (
        <Suspense fallback={<Loading />}>
          <ListSubscription
            listId={id}
            onMembershipChange={() => void refresh()}
          />
        </Suspense>
      )}
    </>
  );
}
