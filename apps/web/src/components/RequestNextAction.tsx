import { Link } from "react-router-dom";
import type { components } from "../api/schema";

type Request = components["schemas"]["RequestView"];
type Target = components["schemas"]["TargetView"];

export function requestTargetLabel(target: Target) {
  if (target.next_action === "selected-release") return "Release selected";
  if (target.next_action === "downloads") return "Acquisition pending";
  return (
    {
      wanted: "Wanted",
      satisfied: "Available",
      paused: "Paused",
      cancelled: "Cancelled",
      "awaiting-inventory": "Check inventory",
    }[target.state] || target.state
  );
}

export default function RequestNextAction({
  request,
  target,
}: {
  request: Request;
  target: Target;
}) {
  if (!request.can_open_book) return null;
  switch (target.next_action) {
    case "search":
      return (
        <Link
          to={`/books/${request.work_id}?tab=sources&request=${request.id}&slot=${target.slot}`}
        >
          Choose a source release
        </Link>
      );
    case "selected-release":
      return target.source_artifact_id ? (
        <Link to={`/sources/artifacts/${target.source_artifact_id}`}>
          View selected release
        </Link>
      ) : null;
    case "downloads":
      return <Link to="/requests?status=downloading">View download queue</Link>;
    case "book":
      return (
        <Link to={`/books/${request.work_id}`}>
          {target.state === "satisfied"
            ? "View library copies"
            : "Review book and inventory"}
        </Link>
      );
    default:
      return null;
  }
}
