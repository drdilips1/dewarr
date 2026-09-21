import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result, type Work } from "../api/client";
import { Loading, Notice } from "../components";
import WorkMerge from "../pages/WorkMerge";

export default function BookGrouping({
  work,
  admin,
}: {
  work: Work;
  admin: boolean;
}) {
  const [open, setOpen] = useState(false);
  const cache = useQueryClient();
  const group = useQuery({
    queryKey: ["work-grouping", work.id],
    enabled: open,
    queryFn: async () =>
      result(
        await api.GET("/api/catalog/works/{work_id}/grouping", {
          params: { path: { work_id: work.id } },
        }),
      ),
  });
  const change = useMutation({
    mutationFn: async ({
      id,
      separate,
      revision,
    }: {
      id: string;
      separate: boolean;
      revision: string;
    }) =>
      result(
        await api.PATCH("/api/catalog/works/{work_id}/grouping", {
          params: { path: { work_id: id } },
          body: { separate, expected_revision: revision },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries();
    },
  });
  return (
    <details
      className="panel provenance"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>How these editions are grouped</summary>
      <Notice error={group.error || change.error} />
      {open && group.isPending && <Loading />}
      {group.data && (
        <>
          <p>{group.data.reason}</p>
          {group.data.members.map((member) => (
            <div className="source-attribution" key={member.work.id}>
              <span>
                <Link to={`/books/${member.work.id}?tab=library`}>
                  {member.work.title}
                </Link>
                <small>{member.work.authors.join(", ")}</small>
              </span>
              {admin && (
                <div>
                  <button
                    disabled={change.isPending}
                    onClick={() =>
                      change.mutate({
                        id: member.work.id,
                        separate: !member.separate,
                        revision: member.revision,
                      })
                    }
                  >
                    {member.separate
                      ? "Allow automatic grouping"
                      : "Keep this record separate"}
                  </button>
                  {member.work.id !== work.id && (
                    <WorkMerge work={member.work} targetWork={work} />
                  )}
                </div>
              )}
            </div>
          ))}
          {admin && (
            <p className="muted">
              Separation applies to this catalog record for everyone. Confirming
              the same book uses a merge preview; editions and files stay
              intact.
            </p>
          )}
        </>
      )}
    </details>
  );
}
