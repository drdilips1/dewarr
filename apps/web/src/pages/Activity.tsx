import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import Downloads from "./Downloads";
import DownloadReviews from "./DownloadReviews";
import ActivityRequests from "./ActivityRequests";
import { Notice } from "../components";
import OperationHistory from "./OperationHistory";

export default function Activity({
  admin,
  canRequest,
}: {
  admin: boolean;
  canRequest: boolean;
}) {
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
      <div className="page-heading">
        <div>
          <p className="eyebrow">EVERY STEP, IN VIEW</p>
          <h1>Activity</h1>
          <p className="muted">
            Track requests and see what needs your attention.
          </p>
        </div>
        {admin ? (
          <button onClick={() => probe.mutate()} disabled={probe.isPending}>
            Check background worker
          </button>
        ) : null}
      </div>
      <Downloads canManage={canRequest} />
      <ActivityRequests canManage={canRequest} />
      {admin && <DownloadReviews />}
      <Notice error={probe.error} />
      <OperationHistory />
    </>
  );
}
