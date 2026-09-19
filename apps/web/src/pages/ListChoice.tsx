import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
  const [offset, setOffset] = useState(0);
  const [chosenName, setChosenName] = useState("");
  const lists = useQuery({
    queryKey: ["lists", "choice", search, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/page", {
          params: { query: { editable: true, q: search, offset, limit: 25 } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
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
            setOffset(0);
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
      {lists.data && !lists.error && (offset > 0 || lists.data.total > 25) && (
        <div className="pagination">
          <button
            type="button"
            disabled={disabled || !offset || lists.isFetching}
            onClick={() => setOffset(offset - 25)}
          >
            Previous lists
          </button>
          <span>
            {offset + 1}–{offset + lists.data.items.length} of{" "}
            {lists.data.total}
          </span>
          <button
            type="button"
            disabled={
              disabled || offset + 25 >= lists.data.total || lists.isFetching
            }
            onClick={() => setOffset(offset + 25)}
          >
            Next lists
          </button>
        </div>
      )}
      {lists.data?.total === 0 && (
        <p>
          No matching lists. <Link to="/lists">Create or browse lists</Link>.
        </p>
      )}
    </div>
  );
}
