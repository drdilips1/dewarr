import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Notice } from "../components";
import OperationHistory from "./OperationHistory";

export default function Activity({ admin }: { admin: boolean }) {
  const client = useQueryClient();
  const probe = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/system/probe", {
          params: { header: { "idempotency-key": crypto.randomUUID() } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["activity"] }),
  });
  return (
    <>
      <Notice error={probe.error} />
      <OperationHistory
        actions={
          admin ? (
            <button
              className="logs-worker-check"
              onClick={() => probe.mutate()}
              disabled={probe.isPending}
            >
              {probe.isPending ? "Checking…" : "Check background worker"}
            </button>
          ) : undefined
        }
      />
    </>
  );
}
