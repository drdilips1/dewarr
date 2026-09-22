import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import BookCover from "../components/BookCover";
import { genreLabel } from "../components/DiscoveryCollections";
import FollowRelease, { basisLabel } from "../components/FollowRelease";
import BookLink from "../components/BookLink";
import InfiniteScroll from "../components/InfiniteScroll";
import { usePagedQuery } from "../hooks/usePagedQuery";

type Entry = components["schemas"]["ReleaseEntry"];
type Month = components["schemas"]["ReleaseMonth"];

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month: string, delta: number) {
  const [year, mon] = month.split("-").map(Number);
  return monthKey(new Date(year, mon - 1 + delta, 1));
}

function monthTitle(month: string) {
  const [year, mon] = month.split("-").map(Number);
  return new Date(year, mon - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function entryKey(entry: Entry) {
  return entry.work_id || `${entry.provider}:${entry.external_id}`;
}

function prefer(previous: Entry | undefined, entry: Entry): Entry {
  if (!previous) return entry;
  return {
    ...previous,
    ...entry,
    work_id: previous.work_id || entry.work_id,
    external_id: previous.external_id || entry.external_id,
    followed: Boolean(previous.followed || entry.followed),
    in_library: Boolean(previous.in_library || entry.in_library),
    state: previous.state || entry.state,
    release_date: entry.release_date || previous.release_date,
    basis: entry.release_date ? entry.basis : previous.basis,
    genres: entry.genres?.length ? entry.genres : previous.genres,
  };
}

function mergePages(pages: Month[] | undefined) {
  const items = new Map<string, Entry>();
  const undated = new Map<string, Entry>();
  for (const page of pages || []) {
    for (const entry of page.items || []) {
      const key = entryKey(entry);
      items.set(key, prefer(items.get(key), entry));
    }
    for (const entry of page.undated || []) {
      const key = entryKey(entry);
      undated.set(key, prefer(undated.get(key), entry));
    }
  }
  return {
    items: [...items.values()],
    undated: [...undated.values()],
  };
}

function daysInMonth(month: string) {
  const [year, mon] = month.split("-").map(Number);
  const count = new Date(year, mon, 0).getDate();
  const lead = (new Date(year, mon - 1, 1).getDay() + 6) % 7;
  const cells: Array<{ key: string; day: number } | null> = [
    ...Array.from({ length: lead }, () => null),
  ];
  for (let day = 1; day <= count; day += 1) {
    cells.push({
      key: `${year}-${String(mon).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
      day,
    });
  }
  return cells;
}

function ReleaseBook({ entry, canEdit }: { entry: Entry; canEdit: boolean }) {
  const href = entry.work_id
    ? `/books/${entry.work_id}`
    : entry.external_id
      ? `/discover/books/hardcover/${encodeURIComponent(entry.external_id)}`
      : null;
  return (
    <article className="release-book">
      <BookCover title={entry.title} cover={entry.cover_url} actions={false} />
      <div>
        <h3>{href ? <Link to={href}>{entry.title}</Link> : entry.title}</h3>
        <p>{entry.authors.join(", ") || "Author unknown"}</p>
        <p className="muted">{basisLabel(entry.basis)}</p>
        <p className="muted">
          {[
            entry.followed && "Following",
            entry.in_library && "In library",
            entry.state === "waiting" && "Waiting for release",
            entry.state === "wanted" && "Searching when it matches",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <FollowRelease
          canEdit={canEdit}
          following={entry.followed}
          workId={entry.work_id}
          body={{
            work_id: entry.work_id,
            provider: entry.provider === "hardcover" ? "hardcover" : null,
            external_id: entry.external_id,
            title: entry.title,
            authors: entry.authors,
            cover_url: entry.cover_url,
            release_date: entry.release_date,
            basis: entry.basis,
          }}
        />
      </div>
    </article>
  );
}

export function UpcomingShelf({ canEdit }: { canEdit: boolean }) {
  const query = useQuery({
    queryKey: ["release-upcoming"],
    queryFn: async () => result(await api.GET("/api/releases/upcoming")),
    retry: false,
  });
  const items = (query.data?.items || []).slice(0, 20);
  return (
    <section className="discovery-section" aria-label="Upcoming releases">
      <div className="section-heading discovery-heading">
        <h2>Upcoming releases</h2>
        <Link className="back-link" to="/discover?view=calendar">
          Calendar
        </Link>
      </div>
      <Notice error={query.error} />
      {query.isPending && <Loading />}
      {query.data?.warning && (
        <p className="notice" role="status">
          {query.data.warning}
        </p>
      )}
      {query.data?.status === "not-connected" && (
        <Link className="back-link" to="/settings#catalog">
          Connect Hardcover
        </Link>
      )}
      {query.data?.status === "ready" && items.length === 0 && (
        <p className="muted">
          {query.data.has_more
            ? "More of this month is on the calendar."
            : "No upcoming audiobooks for the genres you follow."}
        </p>
      )}
      {items.length > 0 && (
        <ul className="discovery-shelf" aria-label="Upcoming releases">
          {items.map((item) => (
            <li
              key={
                item.work?.id ||
                `${item.book.provider}:${item.book.external_id}`
              }
            >
              <BookLink
                className="book-card discovery-book"
                to={
                  item.work
                    ? `/books/${item.work.id}`
                    : item.book.external_id
                      ? `/discover/books/hardcover/${encodeURIComponent(item.book.external_id)}`
                      : `/search?q=${encodeURIComponent(item.book.title)}`
                }
                aria-label={`View ${item.book.title}`}
              >
                <BookCover
                  title={item.book.title}
                  cover={item.book.cover_url}
                  actions={false}
                />
                <h3 title={item.book.title}>{item.book.title}</h3>
                <p title={item.book.authors.join(", ")}>
                  {item.book.authors.join(", ") || "Author unknown"}
                </p>
                <p className="muted">{basisLabel(item.book.date_basis)}</p>
              </BookLink>
              <FollowRelease
                canEdit={canEdit}
                workId={item.work?.id}
                body={{
                  work_id: item.work?.id,
                  provider: "hardcover",
                  external_id: item.book.external_id,
                  title: item.book.title,
                  authors: item.book.authors,
                  cover_url: item.book.cover_url,
                  release_date: item.book.release_date,
                  basis: item.book.date_basis,
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function ReleaseCalendar({ canEdit }: { canEdit: boolean }) {
  const cache = useQueryClient();
  const [month, setMonth] = useState(() => monthKey(new Date()));
  const query = usePagedQuery({
    queryKey: ["release-calendar", month],
    queryFn: async (page, signal) =>
      result(
        await api.GET("/api/releases/calendar", {
          params: { query: { month, page } },
          signal,
        }),
      ),
    next: (last, pages) =>
      last.has_more && pages.length < 25 ? pages.length + 1 : undefined,
    retry: false,
  });
  const saveGenres = useMutation({
    mutationFn: async (genres: string[]) =>
      result(await api.PUT("/api/releases/genres", { body: { genres } })),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["release-calendar"] });
      await cache.invalidateQueries({ queryKey: ["release-upcoming"] });
    },
  });
  const data: Month | undefined = query.data;
  const merged = useMemo(
    () => mergePages(query.loadedPages),
    [query.loadedPages],
  );
  const byDay = useMemo(() => {
    const grouped = new Map<string, Entry[]>();
    for (const item of merged.items) {
      if (!item.release_date) continue;
      grouped.set(item.release_date, [
        ...(grouped.get(item.release_date) || []),
        item,
      ]);
    }
    return grouped;
  }, [merged.items]);
  const cells = daysInMonth(data?.month || month);
  function toggleGenre(genre: string) {
    const selected = new Set(data?.genres || []);
    if (selected.has(genre)) selected.delete(genre);
    else selected.add(genre);
    saveGenres.mutate([...selected]);
  }
  return (
    <section className="release-calendar" aria-label="Upcoming releases">
      <div className="explore-view-heading">
        <div>
          <h1>Calendar</h1>
          <p className="muted">
            Audiobook release days for the genres you follow. A work date is
            labeled when the audiobook day is still unknown.
          </p>
        </div>
        <div className="button-row">
          <button
            type="button"
            aria-label="Previous month"
            onClick={() => setMonth((current) => shiftMonth(current, -1))}
          >
            <ChevronLeft size={16} />
          </button>
          <strong>{monthTitle(data?.month || month)}</strong>
          <button
            type="button"
            aria-label="Next month"
            onClick={() => setMonth((current) => shiftMonth(current, 1))}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      <fieldset className="release-genres">
        <legend>Genres to discover</legend>
        <div>
          {(data?.choices || []).map((genre) => (
            <label key={genre}>
              <input
                type="checkbox"
                checked={data?.genres.includes(genre) || false}
                disabled={!canEdit || saveGenres.isPending || !data}
                onChange={() => toggleGenre(genre)}
              />
              {genreLabel(genre)}
            </label>
          ))}
        </div>
      </fieldset>
      <Notice error={query.error || saveGenres.error} />
      {data?.warning && (
        <p className="notice" role="status">
          {data.warning}
        </p>
      )}
      {query.isPending && <Loading />}
      {data &&
        !merged.items.length &&
        !merged.undated.length &&
        !query.hasNextPage && (
          <p className="muted">Nothing is scheduled this month.</p>
        )}
      {query.hasNextPage && !merged.items.length && (
        <InfiniteScroll query={query} manual />
      )}
      {data && (
        <>
          <div className="release-weekdays" aria-hidden="true">
            {WEEKDAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="release-month">
            {cells.map((cell, index) =>
              cell ? (
                <section
                  key={cell.key}
                  className="release-day"
                  aria-label={cell.key}
                >
                  <h2>{cell.day}</h2>
                  <ul className="release-marks">
                    {(byDay.get(cell.key) || []).map((entry) => {
                      const mark =
                        entry.work_id ||
                        `${entry.provider}:${entry.external_id}`;
                      return (
                        <li key={mark}>
                          <a href={`#release-${mark}`}>{entry.title}</a>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : (
                <div key={`pad-${index}`} className="release-pad" />
              ),
            )}
          </div>
          {merged.items.some((entry) => entry.release_date) && (
            <ul className="release-agenda">
              {merged.items
                .filter((entry) => entry.release_date)
                .sort((left, right) =>
                  (left.release_date || "").localeCompare(
                    right.release_date || "",
                  ),
                )
                .map((entry) => {
                  const mark =
                    entry.work_id || `${entry.provider}:${entry.external_id}`;
                  return (
                    <li key={mark} id={`release-${mark}`}>
                      <p className="muted">{entry.release_date}</p>
                      <ReleaseBook entry={entry} canEdit={canEdit} />
                    </li>
                  );
                })}
            </ul>
          )}
          {merged.undated.length > 0 && (
            <section aria-label="Undated upcoming books">
              <h2>Undated upcoming</h2>
              <p className="muted">
                These are marked coming soon and do not have a full release day
                yet.
              </p>
              <ul className="release-undated">
                {merged.undated.map((entry) => (
                  <li
                    key={
                      entry.work_id || `${entry.provider}:${entry.external_id}`
                    }
                  >
                    <ReleaseBook entry={entry} canEdit={canEdit} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          {query.hasNextPage && merged.items.length > 0 && (
            <InfiniteScroll query={query} manual />
          )}
        </>
      )}
    </section>
  );
}
