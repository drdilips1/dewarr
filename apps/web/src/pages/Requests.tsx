import { lazy, Suspense } from "react";
import {
  ArrowUpDown,
  ClipboardCheck,
  Clock,
  Download,
  Library,
  List,
  Undo2,
  X,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Loading } from "../components";
import { usePendingApprovals } from "../hooks/usePendingApprovals";
import { requestFilter, type RequestFilter } from "./requestFilters";

const SavedRequests = lazy(() => import("./ActivityRequests"));

const filters: {
  id: RequestFilter;
  title: string;
  icon: typeof List;
  approve?: boolean;
  admin?: boolean;
}[] = [
  { id: "all", title: "All", icon: List },
  { id: "pending", title: "Pending", icon: Clock, approve: true },
  { id: "downloading", title: "Downloading", icon: Download },
  { id: "library", title: "In library", icon: Library },
  { id: "declined", title: "Declined", icon: X },
  { id: "withdrawn", title: "Withdrawn", icon: Undo2 },
  { id: "review", title: "Review", icon: ClipboardCheck, admin: true },
];

export default function Requests({
  admin,
  canRequest,
  canApprove,
}: {
  admin: boolean;
  canRequest: boolean;
  canApprove: boolean;
}) {
  const { hash, search } = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(search);
  const selected = requestFilter(hash, params.get("status"));
  const sort = params.get("sort") === "title" ? "title" : "newest";
  const pendingApprovals = usePendingApprovals(canApprove);
  const waiting = pendingApprovals.data?.total ?? 0;
  const visible = filters.filter(
    (filter) => (!filter.approve || canApprove) && (!filter.admin || admin),
  );
  const status =
    (selected === "review" && !admin) || (selected === "pending" && !canApprove)
      ? "all"
      : selected;

  function visit(nextStatus: RequestFilter, nextSort = sort) {
    const next = new URLSearchParams(search);
    if (nextStatus === "all") next.delete("status");
    else next.set("status", nextStatus);
    if (nextSort === "newest") next.delete("sort");
    else next.set("sort", nextSort);
    const query = next.toString();
    navigate(query ? `/requests?${query}` : "/requests");
  }

  return (
    <div className="requests-page">
      <h1 className="sr-only">Requests</h1>
      <div className="page-view-toolbar requests-toolbar">
        <nav className="request-filters" aria-label="Request filters">
          {visible.map((filter) => {
            const Icon = filter.icon;
            return (
              <button
                key={filter.id}
                type="button"
                aria-pressed={status === filter.id}
                onClick={() => visit(filter.id)}
              >
                <Icon size={15} aria-hidden />
                {filter.title}
                {filter.id === "pending" && waiting > 0 && (
                  <span className="requests-tab-count">
                    {waiting > 99 ? "99+" : waiting}
                    <span className="sr-only"> waiting</span>
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <label className="request-sort">
          <ArrowUpDown size={15} aria-hidden />
          <span className="sr-only">Sort</span>
          <select
            aria-label="Sort requests"
            value={sort}
            onChange={(event) =>
              visit(status, event.target.value === "title" ? "title" : "newest")
            }
          >
            <option value="newest">Newest</option>
            <option value="title">Title</option>
          </select>
        </label>
        <Link className="page-view-action" to="/discover">
          Find books
        </Link>
      </div>
      <Suspense fallback={<Loading />}>
        <SavedRequests canManage={canRequest} status={status} sort={sort} />
      </Suspense>
    </div>
  );
}
