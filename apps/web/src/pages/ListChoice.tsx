import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";

export default function ListChoice({
  value,
  onChange,
  label,
  disabled = false,
}: {
  value: string;
  onChange: (id: string) => void;
  label: string;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [chosenName, setChosenName] = useState("");
  const lists = usePagedQuery({
    queryKey: ["lists", "choice", search],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/lists/page", {
          signal,
          params: { query: { editable: true, q: search, offset, limit: 25 } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  return (
    <div className="grow">
      <label>
        Find lists by name
        <input
          value={search}
          disabled={disabled}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
      </label>
      <Notice error={lists.error} />
      <label>
        {label}
        <select
          aria-label={label}
          value={value}
          required
          disabled={disabled || lists.isFetching || !!lists.error}
          onChange={(event) => {
            setChosenName(
              lists.data?.items.find((list) => list.id === event.target.value)
                ?.name || "",
            );
            onChange(event.target.value);
          }}
        >
          <option value="">Choose a list</option>
          {!lists.error &&
            value &&
            !lists.data?.items.some((list) => list.id === value) && (
              <option value={value}>{chosenName || "Selected list"}</option>
            )}
          {!lists.error &&
            lists.data?.items.map((list) => (
              <option value={list.id} key={list.id}>
                {list.name}
              </option>
            ))}
        </select>
      </label>
      <InfiniteScroll query={lists} />
      {lists.data?.total === 0 && (
        <p>
          No matching lists. <Link to="/lists">Create or browse lists</Link>.
        </p>
      )}
    </div>
  );
}
