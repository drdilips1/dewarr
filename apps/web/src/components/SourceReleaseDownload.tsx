import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { randomUUID } from "../randomUUID";

export default function SourceReleaseDownload({
  searchId,
  resultId,
  title,
  disabled,
  offerWedge = false,
}: {
  searchId: string;
  resultId: string;
  title: string;
  disabled: boolean;
  offerWedge?: boolean;
}) {
  const key = useRef(randomUUID());
  const cache = useQueryClient();
  const [operationId, setOperationId] = useState<string>();
  const [useWedge, setUseWedge] = useState(false);
  const start = useMutation({
    mutationFn: async (spendWedge: boolean) =>
      result(
        await api.POST(
          "/api/source-searches/{search_id}/results/{result_id}/download",
          {
            params: {
              path: { search_id: searchId, result_id: resultId },
              header: { "idempotency-key": key.current },
              query: spendWedge ? { use_wedge: true } : {},
            },
          },
        ),
      ),
    onSuccess: (operation) => {
      setOperationId(operation.id);
      void cache.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  const status = useQuery({
    queryKey: ["source-release-download", operationId],
    enabled: !!operationId,
    queryFn: async () => {
      const value = result(
        await api.GET("/api/acquisition/automatic-selections/{operation_id}", {
          params: { path: { operation_id: operationId! } },
        }),
      );
      if (!["queued", "running"].includes(value.status)) {
        for (const name of ["requests", "downloads", "activity"])
          void cache.invalidateQueries({ queryKey: [name] });
      }
      return value;
    },
    refetchInterval: (query) =>
      query.state.data &&
      !["queued", "running"].includes(query.state.data.status)
        ? false
        : 1500,
  });
  const receipt = status.data || start.data;
  const busy =
    start.isPending ||
    (!!receipt && ["queued", "running"].includes(receipt.status));
  const complete = receipt?.status === "completed";
  const message =
    start.error?.message || status.error?.message || receipt?.message;
  return (
    <div className="source-row-download">
      {offerWedge && (
        <label className="check-label wedge-choice">
          <input
            type="checkbox"
            checked={useWedge}
            disabled={disabled || busy}
            onChange={(event) => {
              setUseWedge(event.target.checked);
              if (!busy) {
                key.current = randomUUID();
                setOperationId(undefined);
              }
            }}
          />
          Use a Freeleech wedge
        </label>
      )}
      <button
        className="release-info-button"
        aria-label={`Download ${title}`}
        title={complete ? "Download started" : "Download this release"}
        disabled={disabled || busy || complete}
        onClick={() => {
          if (receipt && !busy) {
            key.current = randomUUID();
            setOperationId(undefined);
          }
          start.mutate(offerWedge && useWedge);
        }}
      >
        {busy ? (
          <LoaderCircle size={18} className="source-download-spinner" />
        ) : (
          <Download size={18} />
        )}
      </button>
      {message && (
        <span
          className="source-download-message"
          role={start.error || status.error ? "alert" : "status"}
        >
          {message} {receipt && <Link to="/requests">View downloads</Link>}
        </span>
      )}
    </div>
  );
}
