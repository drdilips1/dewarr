import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Empty, Loading, Notice } from "../components";
import DiscoveryShelf from "../components/DiscoveryShelf";
import { Preview } from "./ProviderSearch";

type Card = components["schemas"]["CommunityListCard"];

export default function CommunityLists({ canEdit }: { canEdit: boolean }) {
  const { externalId } = useParams();
  return externalId ? (
    <ListPreview key={externalId} externalId={externalId} canEdit={canEdit} />
  ) : (
    <CommunityIndex />
  );
}

function Covers({ list }: { list: Card }) {
  return (
    <div className="community-covers" aria-hidden="true">
      {list.covers.length ? (
        list.covers.map((cover, index) => (
          <img
            key={`${cover}:${index}`}
            src={cover}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        ))
      ) : (
        <BookOpen size={36} />
      )}
    </div>
  );
}

function CommunityIndex() {
  const [params, setParams] = useSearchParams();
  const term = params.get("q") || "";
  const page = Math.min(50, Math.max(1, Number(params.get("page")) || 1));
  const navigate = useNavigate();
  const account = useQuery({
    queryKey: ["metadata-account"],
    queryFn: async () => result(await api.GET("/api/metadata/account")),
  });
  const query = useQuery({
    queryKey: ["community-lists", term, page],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/lists", {
          params: { query: { q: term, page } },
        }),
      ),
    enabled: !!account.data?.enabled,
    gcTime: 0,
    retry: false,
  });
  return (
    <>
      <Link className="back-link" to="/discover">
        ← Discover
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CURATED BY READERS</p>
          <h1>Community lists</h1>
          <p className="muted">
            Explore public Hardcover lists, preview the books, and follow your
            favorites.
          </p>
        </div>
      </div>
      <Notice error={account.error} />
      {account.isPending && <Loading />}
      {account.data && !account.data.enabled && (
        <section className="panel">
          <h2>Connect Hardcover to explore lists</h2>
          <p className="muted">
            Your account connects these lists to your catalog and private
            subscriptions.
          </p>
          <Link className="back-link" to="/metadata">
            Connect Hardcover
          </Link>
        </section>
      )}
      {account.data?.enabled && (
        <>
          <form
            className="panel inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              const value = String(
                new FormData(event.currentTarget).get("q") || "",
              ).trim();
              setParams(value ? { q: value } : {});
            }}
          >
            <label className="grow">
              Search public lists
              <input
                key={term}
                name="q"
                defaultValue={term}
                maxLength={150}
                placeholder="A genre, reading challenge, or theme"
              />
            </label>
            <button className="primary">Search lists</button>
            {term && (
              <button type="button" onClick={() => setParams({})}>
                Clear search
              </button>
            )}
          </form>
          <details className="panel community-direct">
            <summary>Have a Hardcover list ID?</summary>
            <form
              className="inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                const id = String(
                  new FormData(event.currentTarget).get("listId") || "",
                );
                navigate(`/discover/lists/${id}`);
              }}
            >
              <label className="grow">
                Public list ID
                <input
                  name="listId"
                  inputMode="numeric"
                  pattern="[1-9][0-9]{0,9}"
                  required
                />
              </label>
              <button>Preview list</button>
            </form>
          </details>
          <p className="muted">
            {term
              ? "Search relevance from Hardcover. Only currently public lists are shown."
              : "Public lists ordered by reported Hardcover follower count."}
          </p>
          <Notice error={query.error} />
          {query.isPending && <Loading />}
          {query.error && (
            <button onClick={() => query.refetch()} disabled={query.isFetching}>
              Retry lists
            </button>
          )}
          {query.data && !query.error && (
            <>
              {query.data.warning && (
                <p className="notice" role="status">
                  {query.data.warning}
                </p>
              )}
              {query.data.items.length ? (
                <div className="list-grid community-grid">
                  {query.data.items.map((list) => (
                    <Link
                      className="list-card panel community-card"
                      key={list.external_id}
                      to={`/discover/lists/${list.external_id}`}
                    >
                      <Covers list={list} />
                      <h2>{list.name}</h2>
                      <p>
                        {list.count.toLocaleString()} books
                        {list.followers != null
                          ? ` · ${list.followers.toLocaleString()} followers`
                          : ""}
                      </p>
                      {list.description && (
                        <p className="community-description">
                          {list.description}
                        </p>
                      )}
                      {list.followed_list_id && (
                        <span className="status owned">Following</span>
                      )}
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty title="No public lists on this page">
                  Try another search or open a public list by its ID.
                </Empty>
              )}
              {(page > 1 || query.data.has_more) && (
                <div className="pagination" aria-label="Community list pages">
                  <button
                    disabled={page === 1 || query.isFetching}
                    onClick={() =>
                      setParams({ q: term, page: String(page - 1) })
                    }
                  >
                    Previous lists
                  </button>
                  <span role="status">Page {page}</span>
                  <button
                    disabled={
                      !query.data.has_more || page >= 50 || query.isFetching
                    }
                    onClick={() =>
                      setParams({ q: term, page: String(page + 1) })
                    }
                  >
                    Next lists
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}

function ListPreview({
  externalId,
  canEdit,
}: {
  externalId: string;
  canEdit: boolean;
}) {
  const [cursors, setCursors] = useState([0]);
  const [selected, setSelected] = useState<string | null>(null);
  const [key] = useState(() => crypto.randomUUID());
  const trigger = useRef<HTMLButtonElement | null>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
  const cursor = cursors[cursors.length - 1];
  const query = useQuery({
    queryKey: ["community-lists", externalId, cursor],
    queryFn: async () =>
      result(
        await api.GET("/api/discovery/lists/{external_id}", {
          params: { path: { external_id: externalId }, query: { cursor } },
        }),
      ),
    gcTime: 0,
    retry: false,
  });
  const follow = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/discovery/lists/{external_id}/follow", {
          params: {
            path: { external_id: externalId },
            header: { "idempotency-key": key },
          },
          body: {},
        }),
      ),
    onSuccess: (value) => {
      client.invalidateQueries({ queryKey: ["lists"] });
      client.invalidateQueries({ queryKey: ["community-lists"] });
      navigate(`/lists/${value.list_id}`);
    },
  });
  const data = query.error ? undefined : query.data;
  return (
    <>
      <Link className="back-link" to="/discover/lists">
        ← Community lists
      </Link>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.error && (
        <button onClick={() => query.refetch()} disabled={query.isFetching}>
          Retry preview
        </button>
      )}
      {data && (
        <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">PUBLIC LIST · HARDCOVER</p>
              <h1>{data.info.name}</h1>
              <p className="muted">
                {data.info.count.toLocaleString()} books
                {data.info.followers != null
                  ? ` · ${data.info.followers.toLocaleString()} followers`
                  : ""}
              </p>
            </div>
          </div>
          {data.info.description && (
            <p className="description">{data.info.description}</p>
          )}
          <section
            className="panel community-follow"
            aria-label="Follow this list"
          >
            <div>
              <h2>
                {data.info.followed_list_id
                  ? "Already in your lists"
                  : "Keep this list on your shelf"}
              </h2>
              <p className="muted">
                Following creates a private subscription. Downloads stay off
                until you enable automation in its list settings.
              </p>
            </div>
            {data.info.followed_list_id ? (
              <Link
                className="back-link"
                to={`/lists/${data.info.followed_list_id}`}
              >
                Open followed list →
              </Link>
            ) : canEdit ? (
              <button
                className="primary"
                onClick={() => follow.mutate()}
                disabled={follow.isPending || !data.info.follow_supported}
              >
                {follow.isPending ? "Following…" : "Follow list"}
              </button>
            ) : (
              <p className="muted">
                A member account is required to follow lists.
              </p>
            )}
            {!data.info.follow_supported && !data.info.followed_list_id && (
              <p className="notice">
                This list exceeds the supported 5,000-book sync limit. You can
                still browse its preview.
              </p>
            )}
            <Notice error={follow.error} />
          </section>
          {selected && (
            <Preview
              key={selected}
              provider="hardcover"
              externalId={selected}
              canEdit={canEdit}
              onClose={() => {
                setSelected(null);
                trigger.current?.focus();
              }}
            />
          )}
          <section
            className="discovery-section"
            aria-label="Books in this community list"
          >
            <DiscoveryShelf
              shelf={{
                title: "Inside this list",
                attribution: "Included in this Hardcover community list",
                status: "ready",
                page: cursors.length,
                stale: false,
                items: data.items,
                has_more: !!data.next_cursor,
                warning: data.warning,
              }}
              onPreview={(item, button) => {
                if (item.book.external_id) {
                  trigger.current = button;
                  setSelected(item.book.external_id);
                }
              }}
            />
            <p className="muted">
              This is a preview. Following verifies the complete membership
              before automation can be activated.
            </p>
            {(cursors.length > 1 || data.next_cursor != null) && (
              <div className="pagination" aria-label="Community book pages">
                <button
                  disabled={cursors.length === 1 || query.isFetching}
                  onClick={() => setCursors(cursors.slice(0, -1))}
                >
                  Previous books
                </button>
                <span role="status">Page {cursors.length}</span>
                <button
                  disabled={data.next_cursor == null || query.isFetching}
                  onClick={() => {
                    if (data.next_cursor != null)
                      setCursors([...cursors, data.next_cursor]);
                  }}
                >
                  Next books
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
