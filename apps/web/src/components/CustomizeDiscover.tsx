import { useState } from "react";
import { ArrowDown, ArrowUp, Check, Plus, Search } from "lucide-react";
import BookDialog from "./BookDialog";
import DiscoverShelfOrder from "./DiscoverShelfOrder";
import { Notice } from "../components";

export type DiscoverShelfOption = { id: string; title: string; source: string };
export type DiscoverLayout = { order: string[]; hidden: string[] };

export default function CustomizeDiscover({
  shelves,
  initial,
  close,
  save,
  busy,
  error,
}: {
  shelves: DiscoverShelfOption[];
  initial: DiscoverLayout;
  close: () => void;
  save: (layout: DiscoverLayout) => void;
  busy: boolean;
  error: unknown;
}) {
  const [draft, setDraft] = useState(initial);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("All lists");
  const [picking, setPicking] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const selected = draft.order
    .map((id) => shelves.find((s) => s.id === id))
    .filter((s) => !!s);
  const available = shelves.filter(
    (s) =>
      (!draft.order.includes(s.id) || draft.hidden.includes(s.id)) &&
      (source === "All lists" || s.source === source) &&
      s.title.toLowerCase().includes(search.toLowerCase()),
  );
  function reorder(order: string[]) {
    setDraft((d) => ({ ...d, order }));
    setAnnouncement("Shelf order updated.");
  }
  return (
    <BookDialog
      title="Customize Discover"
      className="discover-customizer"
      close={() => {
        if (!busy) close();
      }}
    >
      <div className="customize-intro">
        <div>
          <h2>Make room for your next read.</h2>
          <p>
            Drag shelves into order, or use the arrows. Check the ones you want
            to see.
          </p>
        </div>
        <span>
          {selected.filter((s) => !draft.hidden.includes(s.id)).length} visible
        </span>
      </div>
      <fieldset disabled={busy} className="customize-fields">
        <div className="customize-section-heading">
          <h3>Your shelves</h3>
          <div className="customize-toolbar">
            <button
              type="button"
              className="customize-show-all"
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  hidden: d.hidden.filter((id) => !d.order.includes(id)),
                }))
              }
            >
              <Check size={14} /> Show all shelves
            </button>
            <button
              type="button"
              onClick={() => setPicking(!picking)}
              aria-expanded={picking}
            >
              <Plus size={15} /> Add shelves
            </button>
          </div>
        </div>
        {picking && (
          <section className="customize-picker" aria-label="Add shelves">
            <div className="customize-search">
              <Search size={16} />
              <input
                aria-label="Search available shelves"
                placeholder="Search saved lists and collections"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="customize-filters" aria-label="List sources">
              {[
                "All lists",
                "Your lists",
                "Community lists",
                "Master lists",
              ].map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={source === value}
                  onClick={() => setSource(value)}
                >
                  {value}
                </button>
              ))}
            </div>
            <ul className="customize-options">
              {available.map((s) => (
                <li key={s.id}>
                  <div>
                    <strong>{s.title}</strong>
                    <small>{s.source}</small>
                  </div>
                  <button
                    type="button"
                    aria-label={`Add ${s.title}`}
                    disabled={draft.order.length >= 200}
                    onClick={() => {
                      setDraft((d) => ({
                        order: d.order.includes(s.id)
                          ? d.order
                          : [...d.order, s.id],
                        hidden: d.hidden.filter((id) => id !== s.id),
                      }));
                      setAnnouncement(`${s.title} added.`);
                    }}
                  >
                    <Plus size={16} /> Add
                  </button>
                </li>
              ))}
            </ul>
            {!available.length && (
              <p className="muted">
                {search
                  ? "No lists match your search."
                  : "All available shelves in this category are already added."}
              </p>
            )}
            <p className="customize-picker-note">
              Includes your saved community and custom lists, plus the master
              collection catalog.
            </p>
          </section>
        )}
        <div className="customize-columns">
          <span>Shelf order</span>
          <span>Show</span>
        </div>
        <DiscoverShelfOrder
          itemLabel={(id) => shelves.find((s) => s.id === id)?.title || id}
          values={selected.map((s) => s.id)}
          disabled={busy}
          onChange={reorder}
          render={(id) => {
            const shelf = shelves.find((s) => s.id === id)!;
            const index = draft.order.indexOf(id);
            return (
              <>
                <div className="customize-shelf-name">
                  <strong>{shelf.title}</strong>
                  <small>{shelf.source}</small>
                </div>
                <div className="customize-arrows">
                  {[-1, 1].map((direction) => (
                    <button
                      key={direction}
                      type="button"
                      aria-label={`Move ${shelf.title} ${direction < 0 ? "up" : "down"}`}
                      disabled={
                        busy ||
                        index + direction < 0 ||
                        index + direction >= draft.order.length
                      }
                      onClick={() => {
                        const order = [...draft.order];
                        [order[index], order[index + direction]] = [
                          order[index + direction],
                          order[index],
                        ];
                        reorder(order);
                      }}
                    >
                      {direction < 0 ? (
                        <ArrowUp size={16} />
                      ) : (
                        <ArrowDown size={16} />
                      )}
                    </button>
                  ))}
                </div>
                <input
                  className="customize-visibility"
                  type="checkbox"
                  aria-label={shelf.title}
                  checked={!draft.hidden.includes(id)}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setDraft((d) => ({
                      ...d,
                      hidden: checked
                        ? d.hidden.filter((v) => v !== id)
                        : [...d.hidden, id],
                    }));
                  }}
                />
              </>
            );
          }}
        />
      </fieldset>
      <p className="sr-only" role="status">
        {announcement}
      </p>
      <Notice error={error instanceof Error ? error : null} />
      <footer className="customize-footer">
        <span>Changes apply when you save.</span>
        <div>
          <button disabled={busy} onClick={close}>
            Cancel
          </button>
          <button
            className="primary"
            disabled={busy}
            onClick={() => save(draft)}
          >
            {busy ? "Saving…" : "Save layout"}
          </button>
        </div>
      </footer>
    </BookDialog>
  );
}
