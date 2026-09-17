import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, Check, Headphones } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, result } from "../api/client";
import { LibraryAssets } from "./MyLibrary";
import { Loading, Notice } from "../components";
import BookMetadata from "./BookMetadata";

export default function BookDetail({
  canEdit,
  admin,
}: {
  canEdit: boolean;
  admin: boolean;
}) {
  const { id = "" } = useParams();
  const [listId, setListId] = useState("");
  const [saved, setSaved] = useState(false);
  const book = useQuery({
    queryKey: ["work", id],
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works/{work_id}", {
          params: { path: { work_id: id } },
        }),
      ),
  });
  const lists = useQuery({
    queryKey: ["lists"],
    queryFn: async () => result(await api.GET("/api/lists")),
    enabled: canEdit,
  });
  const add = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/entries", {
          params: { path: { list_id: listId } },
          body: { work_id: id },
        }),
      ),
    onSuccess: () => setSaved(true),
  });
  if (book.isPending) return <Loading />;
  if (!book.data) return <Notice error={book.error} />;
  const work = book.data;
  return (
    <>
      <Link to="/" className="back-link">
        <ArrowLeft size={16} />
        Back to catalog
      </Link>
      <div className="book-detail">
        {work.cover_url ? (
          <img
            className="detail-cover"
            src={work.cover_url}
            alt={`Cover of ${work.title}`}
            referrerPolicy="no-referrer"
          />
        ) : (
          <div className="detail-cover type-cover">
            <BookOpen size={34} />
            <span>{work.title}</span>
            <small>{work.authors.join(" · ")}</small>
          </div>
        )}
        <div>
          <p className="eyebrow">
            {work.provisional ? "CATALOG ENTRY" : "BOOK"}
          </p>
          <h1>{work.title}</h1>
          <p className="author-line">
            {work.authors.join(", ") || "Author unknown"}
          </p>
          <div className="status-row">
            <span
              className={work.availability.owned ? "status owned" : "status"}
            >
              {work.availability.owned ? (
                <>
                  <Check size={16} />
                  In library
                </>
              ) : (
                "Not confirmed in library"
              )}
            </span>
            {work.availability.ebook ? (
              <span className="status">
                <BookOpen size={16} />
                Ebook available
              </span>
            ) : null}
            {work.availability.audio ? (
              <span className="status">
                <Headphones size={16} />
                Audiobook available
              </span>
            ) : null}
          </div>
          {work.availability.stale && (
            <p className="muted">
              Last known availability. The library needs a fresh sync.
            </p>
          )}
          <p className="description">
            {work.description || "No description has been added to this title."}
          </p>
          {canEdit ? (
            <form
              className="panel"
              onSubmit={(e) => {
                e.preventDefault();
                add.mutate();
              }}
            >
              <h2>Add to a list</h2>
              <Notice error={lists.error || add.error} />
              {lists.data?.some((list) => list.editable) ? (
                <div className="inline-form">
                  <label className="grow">
                    Reading list
                    <select
                      value={listId}
                      onChange={(e) => {
                        setListId(e.target.value);
                        setSaved(false);
                      }}
                      required
                    >
                      <option value="">Choose a list</option>
                      {lists.data
                        .filter((list) => list.editable)
                        .map((list) => (
                          <option key={list.id} value={list.id}>
                            {list.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <button className="primary" disabled={add.isPending}>
                    Add to list
                  </button>
                </div>
              ) : (
                <p className="muted">
                  <Link to="/lists">Create a reading list</Link> to save this
                  title.
                </p>
              )}
              {saved ? (
                <p className="success" role="status">
                  Added to your list.
                </p>
              ) : null}
            </form>
          ) : null}
        </div>
      </div>
      <BookMetadata work={work} admin={admin} />
      <h2 className="library-access">Your library copies</h2>
      <LibraryAssets workId={id} admin={admin} />
    </>
  );
}
