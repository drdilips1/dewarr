import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";
import BookDialog from "../components/BookDialog";
import {
  CollectionBooks,
  collectionPath,
} from "../components/DiscoveryCollections";
import type { components } from "../api/schema";

type Preview =
  | { type: "collection"; data: components["schemas"]["CollectionDetail"] }
  | { type: "personal"; data: components["schemas"]["PersonalListPreview"] };

function storygraphHost(hostname: string) {
  return (
    hostname === "app.thestorygraph.com" ||
    hostname === "www.thestorygraph.com" ||
    hostname === "thestorygraph.com"
  );
}
export default function AddDiscoveryList({ close }: { close: () => void }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [pinned, setPinned] = useState(true);
  const [tracking, setTracking] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const navigate = useNavigate();
  const cache = useQueryClient();
  let storygraphPaste = false;
  try {
    storygraphPaste = storygraphHost(new URL(url).hostname);
  } catch {
    storygraphPaste = false;
  }
  const load = useMutation({
    mutationFn: async (): Promise<Preview> => {
      const parsed = new URL(url);
      if (storygraphHost(parsed.hostname))
        return {
          type: "personal",
          data: result(
            await api.POST("/api/discovery/personal-list/preview", {
              body: { url, tracking: true },
            }),
          ),
        };
      if (!["goodreads.com", "www.goodreads.com"].includes(parsed.hostname))
        throw new Error(
          "Use a Goodreads list or shelf URL, or a StoryGraph shelf or tag link. Hardcover lists are available below.",
        );
      if (/\/choiceawards\/best-books-\d{4}\/?$/.test(parsed.pathname)) {
        navigate(
          `/discover?view=awards&year=${parsed.pathname.match(/\d{4}/)?.[0]}`,
        );
        close();
        throw new Error("Choose an award category.");
      }
      if (/\/review\/list|\/user\/show/.test(parsed.pathname))
        return {
          type: "personal",
          data: result(
            await api.POST("/api/discovery/personal-list/preview", {
              body: { url, tracking: true },
            }),
          ),
        };
      return {
        type: "collection",
        data: result(
          await api.POST("/api/discovery/collections/preview", {
            body: { url },
          }),
        ),
      };
    },
    onSuccess: setPreview,
  });
  const add = useMutation({
    mutationFn: async () => {
      if (preview?.type === "personal") {
        result(
          await api.POST("/api/discovery/personal-list", {
            body: { url, tracking: true },
          }),
        );
        return "/discover?view=yours";
      }
      const value = result(
        await api.POST("/api/discovery/collections", {
          body: { url, pinned, tracking },
        }),
      );
      return collectionPath(value.id);
    },
    onSuccess: (path) => {
      cache.invalidateQueries({ queryKey: ["discovery-collections"] });
      cache.invalidateQueries({ queryKey: ["discovery-layout"] });
      cache.invalidateQueries({ queryKey: ["discovery", "followed-lists"] });
      cache.invalidateQueries({ queryKey: ["reading-subscriptions"] });
      cache.invalidateQueries({ queryKey: ["lists"] });
      close();
      navigate(path);
    },
  });
  const create = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists", {
          body: { name: name.trim(), shared: false },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["lists"] });
      close();
      navigate("/discover?view=yours");
    },
  });
  if (creating)
    return (
      <BookDialog title="Create a list" close={close}>
        <form
          className="explore-add-form"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label>
            List name
            <input
              autoFocus
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Next on the nightstand"
            />
          </label>
          <button
            className="primary"
            disabled={create.isPending || !name.trim()}
          >
            Create list
          </button>
        </form>
        <Notice error={create.error} />
        <p className="explore-footnote">Add books from their book pages.</p>
      </BookDialog>
    );
  return (
    <BookDialog title="Add a list" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load.mutate();
        }}
        className="explore-add-form"
      >
        <label>
          List URL
          <input
            type="url"
            disabled={load.isPending || add.isPending}
            required
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setPreview(null);
              load.reset();
              add.reset();
            }}
            placeholder="https://www.goodreads.com/list/show/…"
            autoFocus
          />
        </label>
        <button className="primary" disabled={load.isPending || add.isPending}>
          {load.isPending ? "Loading…" : "Preview"}
          <ArrowRight size={15} />
        </button>
      </form>
      <p className="explore-footnote">
        Listopia, Choice Awards, a personal Goodreads shelf, or a StoryGraph
        shelf or tag.
      </p>
      <Notice error={load.error || add.error} />
      {preview && (
        <div className="explore-add-preview">
          <h2>
            {preview.type === "collection"
              ? preview.data.collection.title
              : preview.data.name}
          </h2>
          {preview.type === "collection" ? (
            <>
              <p className="muted">
                {preview.data.collection.count.toLocaleString()} books
                {preview.data.collection.coverage === "partial"
                  ? " · Partial preview"
                  : ""}
              </p>
              <CollectionBooks shelf items={preview.data.items.slice(0, 4)} />
              <div className="explore-add-options">
                <label>
                  <input
                    type="checkbox"
                    checked={pinned}
                    onChange={(e) => setPinned(e.target.checked)}
                  />{" "}
                  Show on For you
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={tracking}
                    onChange={(e) => setTracking(e.target.checked)}
                  />{" "}
                  Keep updated
                </label>
              </div>
            </>
          ) : (
            <>
              <p className="muted">
                {storygraphPaste
                  ? `${preview.data.count} ${preview.data.count === 1 ? "book" : "books"} ${preview.data.partial ? "from the pages read so far" : "on this list"}. Later checks add books and leave removed ones here.`
                  : `${preview.data.count} books in the feed. Older books may need a CSV import.`}
              </p>
              <ul>
                {preview.data.titles.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
              <p className="explore-footnote">
                <Check size={13} /> This shelf will be tracked under Your lists.
              </p>
            </>
          )}
          <div className="explore-dialog-actions">
            <span className="muted">Downloads stay off.</span>
            <button
              className="primary"
              disabled={add.isPending}
              onClick={() => add.mutate()}
            >
              <Plus size={15} />
              {add.isPending ? "Adding…" : "Add list"}
            </button>
          </div>
        </div>
      )}
      {!preview && (
        <div className="explore-add-links">
          <button
            type="button"
            onClick={() => {
              close();
              navigate("/discover/lists");
            }}
          >
            Browse Hardcover lists <ArrowRight size={14} />
          </button>
          <button
            type="button"
            onClick={() => {
              close();
              navigate("/settings#reading");
            }}
          >
            Connect reading accounts <ArrowRight size={14} />
          </button>
          <button type="button" onClick={() => setCreating(true)}>
            Create a local list <Plus size={14} />
          </button>
        </div>
      )}
    </BookDialog>
  );
}
