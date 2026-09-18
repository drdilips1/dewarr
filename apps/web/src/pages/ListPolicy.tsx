import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import type { components } from "../api/schema";
import { Loading, Notice } from "../components";
import DownloadConstraints from "./DownloadConstraints";

type Policy = components["schemas"]["ListPolicyView"];
type Input = components["schemas"]["ListPolicyInput"];
type Work = components["schemas"]["WorkView"];

export default function ListPolicy({
  listId,
  works,
}: {
  listId: string;
  works: Work[];
}) {
  const cache = useQueryClient();
  const path = { list_id: listId };
  const policy = useQuery({
    queryKey: ["list-policy", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/acquisition", { params: { path } }),
      ),
    refetchInterval: (query) =>
      query.state.data?.active &&
      query.state.data.configuration.mode === "automatic"
        ? 5000
        : false,
  });
  const [offset, setOffset] = useState(0);
  const books = useQuery({
    queryKey: ["list-policy-books", listId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/acquisition/books", {
          params: { path, query: { offset, limit: 25 } },
        }),
      ),
    refetchInterval:
      policy.data?.active && policy.data.configuration.mode === "automatic"
        ? 5000
        : false,
  });
  const saved = (value: Policy) => {
    cache.setQueryData(["list-policy", listId], value);
    void cache.invalidateQueries({ queryKey: ["list-policy-books", listId] });
  };
  const pause = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/acquisition/pause", {
          params: { path },
          body: { expected_revision: policy.data!.revision },
        }),
      ),
    onSuccess: saved,
  });
  return (
    <section className="panel editor" aria-label="List acquisition policy">
      <h2>List acquisition</h2>
      <p>
        Keep browsing, request books yourself, or automatically acquire missing
        media when books join this list.
      </p>
      <Notice error={policy.error || books.error || pause.error} />
      {policy.isPending ? (
        <Loading />
      ) : policy.isSuccess ? (
        <>
          {policy.data && (
            <>
              <p role="status">
                {policy.data.active
                  ? policy.data.message
                  : "Acquisition paused; list synchronization continues"}
              </p>
              {policy.data.active &&
                policy.data.configuration.mode === "automatic" && (
                  <button
                    onClick={() => pause.mutate()}
                    disabled={pause.isPending}
                  >
                    Pause automatic acquisition
                  </button>
                )}
            </>
          )}
          <PolicyEditor
            key={`${listId}:${policy.data?.revision || 0}`}
            listId={listId}
            works={works}
            policy={policy.data}
            saved={saved}
          />
        </>
      ) : null}
      {!!books.data?.items.length && (
        <details>
          <summary>Monitored books and backlog</summary>
          {books.data.items.map((book) => (
            <article className="source-attribution" key={book.id}>
              <div>
                <Link to={`/books/${book.work_id}`}>{book.title}</Link>
                <p>
                  {book.state} · {book.message}
                </p>
                {book.next_check_at && (
                  <small>
                    Next check: {new Date(book.next_check_at).toLocaleString()}
                  </small>
                )}
              </div>
            </article>
          ))}
          <div className="button-row">
            {offset > 0 && (
              <button onClick={() => setOffset(offset - 25)}>
                Previous monitored books
              </button>
            )}
            {offset + 25 < books.data.total && (
              <button onClick={() => setOffset(offset + 25)}>
                Next monitored books
              </button>
            )}
          </div>
        </details>
      )}
    </section>
  );
}

function PolicyEditor({
  listId,
  works,
  policy,
  saved,
}: {
  listId: string;
  works: Work[];
  policy: Policy | null;
  saved: (value: Policy) => void;
}) {
  const [mode, setMode] = useState<Input["mode"]>(
    (policy?.configuration.mode as Input["mode"]) || "browse",
  );
  const [medium, setMedium] = useState<Input["specification"]["mode"]>(
    policy?.configuration.specification.mode || "either",
  );
  const [preferred, setPreferred] = useState<"ebook" | "audio">(
    policy?.configuration.specification.preferred_medium || "audio",
  );
  const [profileId, setProfileId] = useState(
    policy?.configuration.profile.id || "",
  );
  const [downloaderId, setDownloaderId] = useState(
    policy?.configuration.downloader_id || "",
  );
  const [destinations, setDestinations] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(policy?.configuration.routes || {}).map(([m, r]) => [
        m,
        r.destination_id,
      ]),
    ),
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const key = useRef(crypto.randomUUID());
  const path = { list_id: listId };
  const options = useQuery({
    queryKey: ["selection-options"],
    enabled: mode === "automatic",
    queryFn: async () =>
      result(await api.GET("/api/acquisition/selections/options")),
  });
  const profiles = useQuery({
    queryKey: ["release-profiles"],
    queryFn: async () => result(await api.GET("/api/acquisition/profiles")),
  });
  const downloaders = options.data?.downloaders.filter((d) => d.ready) || [];
  const downloader =
    downloaders.find((d) => d.id === downloaderId) ||
    (downloaders.length === 1 ? downloaders[0] : undefined);
  const media =
    medium === "both" || medium === "either"
      ? (["ebook", "audio"] as const)
      : [medium];
  const available = (m: string) =>
    options.data?.destinations.filter(
      (d) =>
        d.medium === m &&
        d.ready &&
        d.automatic_import_ready &&
        d.source_key === downloader?.source_key,
    ) || [];
  const destination = (m: string) =>
    available(m).find((d) => d.id === destinations[m]) ||
    (available(m).length === 1 ? available(m)[0] : undefined);
  const profile = profiles.data?.find((p) => (p.id || "") === profileId);
  const specification: Input["specification"] = {
    ...policy?.configuration.specification,
    mode: medium,
    preferred_medium: medium === "either" ? preferred : null,
    standalone: policy?.configuration.specification.standalone || false,
    ebook_library_id: null,
    audio_library_id: null,
    // The chosen profile supplies these restrictions; do not carry an old profile's limits into an edit.
    download_constraints: policy?.configuration.request_constraints || null,
  };
  const input: Input = {
    mode,
    specification,
    profile_id: profile?.id || null,
    profile_generation: profile?.generation || 0,
    profile_effective_revision: profile?.effective_revision,
    expected_revision: policy?.revision || 0,
    include_work_ids: mode === "automatic" ? selected : [],
    downloader_id: mode === "automatic" ? downloader?.id : null,
    downloader_generation: mode === "automatic" ? downloader?.generation : null,
    routes:
      mode === "automatic"
        ? Object.fromEntries(
            media.flatMap((m) => {
              const d = destination(m);
              return d
                ? [
                    [
                      m,
                      {
                        destination_id: d.id,
                        destination_revision: d.revision,
                      },
                    ],
                  ]
                : [];
            }),
          )
        : {},
  };
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/acquisition/preview", {
          params: { path, header: { "idempotency-key": key.current } },
          body: input,
        }),
      ),
    onSuccess: (value) => {
      setPreviewId(value.id);
      setOffset(0);
    },
  });
  const receipt = useQuery({
    queryKey: ["list-policy-preview", listId, previewId, offset],
    enabled: !!previewId,
    queryFn: async () =>
      result(
        await api.GET(
          "/api/lists/{list_id}/acquisition/previews/{identifier}",
          {
            params: {
              path: { ...path, identifier: previewId! },
              query: { offset, limit: 50 },
            },
          },
        ),
      ),
  });
  const activate = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/lists/{list_id}/acquisition/previews/{identifier}/activate",
          { params: { path: { ...path, identifier: previewId! } } },
        ),
      ),
    onSuccess: saved,
  });
  const changed = () => {
    key.current = crypto.randomUUID();
    preview.reset();
  };
  return (
    <>
      <Notice
        error={
          options.error ||
          profiles.error ||
          preview.error ||
          receipt.error ||
          activate.error
        }
      />
      {!previewId ? (
        <form
          aria-label="List policy settings"
          onSubmit={(event) => {
            event.preventDefault();
            preview.mutate();
          }}
        >
          <fieldset disabled={preview.isPending}>
            <label>
              Acquisition mode
              <select
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as Input["mode"]);
                  changed();
                }}
              >
                <option value="browse">Browse only</option>
                <option value="manual">Manual requests</option>
                <option value="automatic">Automatic acquisition</option>
              </select>
            </label>
            <label>
              Desired media
              <select
                value={medium}
                onChange={(e) => {
                  setMedium(e.target.value as typeof medium);
                  changed();
                }}
              >
                <option value="ebook">Ebook</option>
                <option value="audio">Audiobook</option>
                <option value="both">Both</option>
                <option value="either">Either medium</option>
              </select>
            </label>
            {medium === "either" && (
              <label>
                Search first
                <select
                  value={preferred}
                  onChange={(e) => {
                    setPreferred(e.target.value as typeof preferred);
                    changed();
                  }}
                >
                  <option value="audio">Audiobook</option>
                  <option value="ebook">Ebook</option>
                </select>
              </label>
            )}
            <label>
              Download profile
              <select
                value={profileId}
                onChange={(e) => {
                  setProfileId(e.target.value);
                  changed();
                }}
              >
                <option value="">Balanced defaults</option>
                {profiles.data
                  ?.filter((p) => p.id)
                  .map((p) => (
                    <option key={p.id} value={p.id || ""}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </label>
            {mode === "automatic" && (
              <>
                <label>
                  Downloader
                  <select
                    value={downloader?.id || ""}
                    onChange={(e) => {
                      setDownloaderId(e.target.value);
                      changed();
                    }}
                  >
                    <option value="">Choose a tested downloader</option>
                    {downloaders.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
                {media.map((m) => (
                  <label key={m}>
                    {m === "audio" ? "Audiobook" : "Ebook"} destination
                    <select
                      value={destination(m)?.id || ""}
                      onChange={(e) => {
                        setDestinations({
                          ...destinations,
                          [m]: e.target.value,
                        });
                        changed();
                      }}
                    >
                      <option value="">Choose an approved destination</option>
                      {available(m).map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
                <p className="muted">
                  Future additions are included. Existing books are excluded
                  unless selected below. Already-owned requested media are
                  skipped. Routes need administrator approval for automatic
                  importing.
                </p>
                <details>
                  <summary>
                    Include current books ({selected.length} selected, maximum
                    25)
                  </summary>
                  <label>
                    Find current books
                    <input
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    />
                  </label>
                  {works
                    .filter((w) =>
                      w.title
                        .toLocaleLowerCase()
                        .includes(filter.toLocaleLowerCase()),
                    )
                    .slice(0, 100)
                    .map((w) => (
                      <label key={w.id}>
                        <input
                          type="checkbox"
                          checked={selected.includes(w.id)}
                          disabled={
                            selected.length >= 25 && !selected.includes(w.id)
                          }
                          onChange={(e) => {
                            setSelected(
                              e.target.checked
                                ? [...selected, w.id]
                                : selected.filter((id) => id !== w.id),
                            );
                            changed();
                          }}
                        />
                        {w.title}
                      </label>
                    ))}
                  <small>
                    Showing up to 100 matching books. Search to narrow a larger
                    list.
                  </small>
                </details>
              </>
            )}
            <button
              className="primary"
              disabled={
                preview.isPending ||
                !profiles.isSuccess ||
                (!!profileId && !profile) ||
                (mode === "automatic" &&
                  (!downloader || media.some((m) => !destination(m))))
              }
            >
              Preview list policy
            </button>
          </fieldset>
        </form>
      ) : receipt.data ? (
        <div aria-label="List activation preview">
          <h3>Review {receipt.data.configuration.mode} mode</h3>
          <p>
            {receipt.data.total} current books · {receipt.data.selected}{" "}
            selected for acquisition.
          </p>
          <p>
            Current books not selected remain in your list. Existing authorized
            work continues when you resume an unchanged policy. Removing a book
            withdraws only this list’s request.
          </p>
          <p>
            Profile: {receipt.data.configuration.profile.name} ·{" "}
            {receipt.data.configuration.specification.mode}
          </p>
          <DownloadConstraints
            value={
              receipt.data.configuration.specification.download_constraints
            }
          />
          {receipt.data.records.map((r) => (
            <article className="source-attribution" key={r.work_id}>
              <div>
                <strong>{r.title}</strong>
                <p>
                  {r.selected ? "Selected" : "Not selected for backlog"} ·{" "}
                  {r.targets.map((t) => `${t.slot}: ${t.state}`).join(" · ")}
                </p>
              </div>
            </article>
          ))}
          <div className="button-row">
            {offset > 0 && (
              <button onClick={() => setOffset(offset - 50)}>
                Previous activation entries
              </button>
            )}
            {offset + 50 < receipt.data.total && (
              <button onClick={() => setOffset(offset + 50)}>
                Next activation entries
              </button>
            )}
            <button
              onClick={() => {
                setPreviewId(null);
                changed();
              }}
            >
              Edit list policy
            </button>
            <button
              className="primary"
              onClick={() => activate.mutate()}
              disabled={activate.isPending}
            >
              {receipt.data.configuration.mode === "automatic"
                ? "Activate automatic acquisition"
                : "Save list mode"}
            </button>
          </div>
        </div>
      ) : (
        <Loading />
      )}
    </>
  );
}
