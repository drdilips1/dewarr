import { lazy, Suspense } from "react";
import { Link, useLocation } from "react-router-dom";
import { Loading } from "../components";
const SavedRequests = lazy(() => import("./ActivityRequests"));
const Downloads = lazy(() => import("./Downloads"));
const Reviews = lazy(() => import("./DownloadReviews"));

export default function Requests({
  admin,
  canRequest,
}: {
  admin: boolean;
  canRequest: boolean;
}) {
  const { hash } = useLocation();
  const tabs = [
    { id: "requests", title: "All requests" },
    { id: "downloads", title: "Download queue" },
    ...(admin ? [{ id: "reviews", title: "Import reviews" }] : []),
  ];
  const active = tabs.find((tab) => `#${tab.id}` === hash)?.id || "requests";
  return (
    <div className="requests-page">
      <h1 className="sr-only">Requests</h1>
      <div className="page-view-toolbar">
        <nav className="requests-tabs" aria-label="Request views">
          {tabs.map((tab) => (
            <Link
              key={tab.id}
              to={`/requests#${tab.id}`}
              aria-current={active === tab.id ? "page" : undefined}
            >
              {tab.title}
            </Link>
          ))}
        </nav>
        <Link className="page-view-action" to="/discover">
          Find books
        </Link>
      </div>
      {active === "reviews" && admin && (
        <p className="requests-review-link">
          <Link className="button" to="/organization/inspections">
            Inspect completed downloads
          </Link>
        </p>
      )}
      <Suspense key={active} fallback={<Loading />}>
        {active === "downloads" ? (
          <Downloads canManage={canRequest} />
        ) : active === "reviews" ? (
          <Reviews />
        ) : (
          <SavedRequests canManage={canRequest} />
        )}
      </Suspense>
    </div>
  );
}
