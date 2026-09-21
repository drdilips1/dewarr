import { ApplicationRelease } from "./components/ApplicationRelease";
import { useRefreshGoodreads } from "./hooks/useRefreshGoodreads";
import { lazy, Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  BookOpen,
  Compass,
  ListPlus,
  RefreshCw,
  LogOut,
  Search,
  Settings,
} from "lucide-react";
import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, ApiError, result, setCsrf } from "./api/client";
import type { Auth } from "./api/client";
import { Loading, Notice } from "./components";

const AddDiscoveryList = lazy(() => import("./pages/AddDiscoveryList"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const GettingStarted = lazy(() => import("./pages/GettingStarted"));
const DiscoverBook = lazy(() => import("./pages/DiscoverBook"));
const Discover = lazy(() => import("./pages/Discover"));
const CommunityLists = lazy(() => import("./pages/CommunityLists"));
const BookDetail = lazy(() => import("./pages/BookDetail"));
const AuthorDetail = lazy(() => import("./pages/AuthorDetail"));
const Series = lazy(() => import("./pages/Series"));
const Lists = lazy(() => import("./pages/Lists"));
const RequestsPage = lazy(() => import("./pages/Requests"));
const SourceArtifact = lazy(() => import("./pages/SourceArtifact"));
const MyLibrary = lazy(() => import("./pages/MyLibrary"));
const ProviderSearch = lazy(() => import("./pages/ProviderSearch"));
const ImportReview = lazy(() => import("./pages/ImportReview"));
const Recovery = lazy(() => import("./pages/Recovery"));

export default function App() {
  const client = useQueryClient();
  useEffect(() => {
    const expire = () => {
      setCsrf("");
      // A new document discards private query caches and outstanding requests.
      window.location.replace("/");
    };
    window.addEventListener("book:session-expired", expire);
    return () => window.removeEventListener("book:session-expired", expire);
  }, [client]);
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await api.GET("/api/auth/me");
      if (response.response.status === 401) return null;
      const auth = result(response);
      setCsrf(auth.csrf_token);
      return auth;
    },
  });
  if (session.isPending) return <Loading />;
  if (session.isError)
    return (
      <main className="auth-page">
        <div className="panel">
          <h1>Unable to connect</h1>
          <Notice error={session.error} />
          <button onClick={() => session.refetch()}>Try again</button>
        </div>
      </main>
    );
  if (!session.data)
    return (
      <SignIn
        onSuccess={(auth) => {
          setCsrf(auth.csrf_token);
          client.setQueryData(["session"], auth);
        }}
      />
    );
  if (session.data.recovery)
    return (
      <Suspense fallback={<Loading />}>
        <Recovery />
      </Suspense>
    );
  return <Shell auth={session.data} />;
}

function SignIn({ onSuccess }: { onSuccess: (auth: Auth) => void }) {
  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: async () => result(await api.GET("/api/auth/setup")),
  });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [token, setToken] = useState("");
  const mutation = useMutation({
    mutationFn: async () => {
      if (setup.data?.needs_setup)
        return result(
          await api.POST("/api/auth/bootstrap", {
            body: {
              username,
              password,
              display_name: displayName,
              bootstrap_token: token,
            },
          }),
        );
      return result(
        await api.POST("/api/auth/login", { body: { username, password } }),
      );
    },
    onSuccess,
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setup.refetch();
    },
  });
  if (setup.isPending) return <Loading />;
  return (
    <main className="auth-page">
      <div className="auth-intro">
        <div className="brand">
          <img src="/assets/dewarr.png" width="32" height="32" alt="" />
          <span>Dewarr</span>
        </div>
        <h1>
          Your next chapter
          <br />
          starts here.
        </h1>
        <p>
          A home for your reading lists.
          <br />A clear view of the books you own.
        </p>
        <div className="spines" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      </div>
      <form
        className="panel auth-form"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <p className="eyebrow">YOUR PERSONAL BOOKSHELF</p>
        <h2>
          {setup.data?.needs_setup ? "Set up your library" : "Welcome back"}
        </h2>
        <p className="muted">
          {setup.data?.needs_setup
            ? "Create the administrator account for this installation."
            : "Sign in to browse your catalog and lists."}
        </p>
        <Notice error={setup.error || mutation.error} />
        {setup.data?.needs_setup ? (
          <label>
            Your name
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
              required
              maxLength={120}
            />
          </label>
        ) : null}
        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            minLength={3}
            maxLength={100}
            pattern="[A-Za-z0-9_.@\-]+"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={
              setup.data?.needs_setup ? "new-password" : "current-password"
            }
            required
            minLength={12}
            maxLength={256}
          />
        </label>
        {setup.data?.needs_setup ? (
          <label>
            Setup token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              minLength={16}
            />
            <small>
              Use the setup token created when this instance was installed.
            </small>
          </label>
        ) : null}
        <button
          className="primary"
          disabled={mutation.isPending || setup.isError}
        >
          {mutation.isPending
            ? "Connecting…"
            : setup.data?.needs_setup
              ? "Create administrator"
              : "Sign in"}
        </button>
      </form>
    </main>
  );
}

function Shell({ auth }: { auth: Auth }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useState("");
  const [addingList, setAddingList] = useState(false);
  const goodreadsRefresh = useRefreshGoodreads();
  useEffect(() => {
    if (location.pathname === "/search")
      setSearch(new URLSearchParams(location.search).get("q") || "");
  }, [location.pathname, location.search]);
  const logout = useMutation({
    mutationFn: async () => result(await api.POST("/api/auth/logout")),
    onSuccess: () => {
      setCsrf("");
      client.clear();
      window.location.assign("/");
    },
  });
  function searchSubmit(event: FormEvent) {
    event.preventDefault();
    navigate("/search?q=" + encodeURIComponent(search.trim()));
  }
  if (
    auth.user.onboarding_status === "pending" &&
    location.pathname !== "/onboarding"
  )
    return <Navigate to="/onboarding" replace />;
  if (location.pathname === "/onboarding")
    return (
      <main className="onboarding-shell">
        <Suspense fallback={<Loading />}>
          <GettingStarted role={auth.user.role} />
        </Suspense>
      </main>
    );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <img src="/assets/dewarr.png" width="32" height="32" alt="" />
          <span>Dewarr</span>
        </NavLink>
        <button
          className="icon-button mobile-signout"
          aria-label="Sign out"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          <LogOut size={18} />
        </button>
        <p className="nav-caption">YOUR COLLECTION</p>
        <nav aria-label="Main navigation">
          <NavLink to="/discover">
            <Compass size={19} />
            Discover
          </NavLink>
          <NavLink to="/library" end>
            <BookOpen size={19} />
            My Library
          </NavLink>
          <NavLink to="/requests">
            <Download size={19} />
            Requests
          </NavLink>
          <NavLink to="/settings">
            <Settings size={19} />
            Settings
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">
            {auth.user.display_name.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{auth.user.display_name}</strong>
            <small>{auth.user.role}</small>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            <LogOut size={18} />
          </button>
        </div>
        <ApplicationRelease />
      </aside>
      <div className="workspace">
        <header className="topbar">
          <form className="search" role="search" onSubmit={searchSubmit}>
            <Search size={18} aria-hidden="true" />
            <input
              aria-label="Search books or authors"
              placeholder="Search books or authors"
              maxLength={300}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button type="submit">Search</button>
          </form>
          {auth.user.role !== "viewer" && (
            <div className="topbar-actions">
              <button
                className="topbar-action"
                onClick={() => setAddingList(true)}
              >
                <ListPlus size={18} aria-hidden="true" />
                Add list
              </button>
              <button
                className="topbar-action"
                aria-label="Refresh Goodreads lists"
                title="Refresh all enabled Goodreads lists"
                disabled={goodreadsRefresh.busy}
                onClick={goodreadsRefresh.refresh}
              >
                <RefreshCw
                  size={18}
                  aria-hidden="true"
                  className={
                    goodreadsRefresh.busy ? "list-refresh-spinning" : undefined
                  }
                />
                <span className="goodreads-refresh-label">
                  {goodreadsRefresh.busy
                    ? "Refreshing…"
                    : "Refresh Goodreads lists"}
                </span>
              </button>
            </div>
          )}
        </header>
        {addingList && (
          <Suspense fallback={<Loading />}>
            <AddDiscoveryList close={() => setAddingList(false)} />
          </Suspense>
        )}
        <main id="main" className="main-content">
          <Notice error={logout.error} />
          <Notice error={goodreadsRefresh.error} />
          {(goodreadsRefresh.busy || goodreadsRefresh.message) && (
            <p role="status">
              {goodreadsRefresh.busy
                ? "Refreshing Goodreads lists…"
                : goodreadsRefresh.message}
            </p>
          )}
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route
                path="/getting-started"
                element={<SettingsRedirect to="/onboarding" />}
              />
              <Route
                path="/settings"
                element={<SettingsPage role={auth.user.role} />}
              />
              <Route
                path="/authors/hardcover/:externalId"
                element={<AuthorDetail />}
              />
              <Route
                path="/discover"
                element={<Discover canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/discover/collections/:collectionId"
                element={<Discover canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/discover/books/:provider/:externalId"
                element={<DiscoverBook canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/discover/lists"
                element={
                  <CommunityLists canEdit={auth.user.role !== "viewer"} />
                }
              />
              <Route
                path="/discover/lists/:externalId"
                element={
                  <CommunityLists canEdit={auth.user.role !== "viewer"} />
                }
              />
              <Route
                path="/download-preferences"
                element={<SettingsRedirect to="/settings#preferences" />}
              />
              <Route path="/" element={<SettingsRedirect to="/library" />} />
              <Route
                path="/books/:id"
                element={
                  <BookDetail
                    canEdit={auth.user.role !== "viewer"}
                    admin={auth.user.role === "admin"}
                  />
                }
              />
              <Route
                path="/search"
                element={
                  <ProviderSearch canEdit={auth.user.role !== "viewer"} />
                }
              />
              <Route
                path="/series/hardcover/:externalId"
                element={<Series canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/metadata"
                element={<SettingsRedirect to="/settings#catalog" />}
              />
              <Route
                path="/sources"
                element={<SettingsRedirect to="/search" />}
              />
              <Route
                path="/sources/audiobookbay"
                element={<SettingsRedirect to="/search" />}
              />
              <Route
                path="/sources/prowlarr"
                element={<SettingsRedirect to="/search" />}
              />
              <Route
                path="/sources/artifacts/:id"
                element={
                  auth.user.role !== "viewer" ? (
                    <SourceArtifact />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route
                path="/downloaders"
                element={<SettingsRedirect to="/settings#downloaders" />}
              />
              <Route
                path="/organization/destinations"
                element={<SettingsRedirect to="/settings#libraries" />}
              />
              <Route
                path="/organization/inspections"
                element={
                  auth.user.role === "admin" ? (
                    <ImportReview />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route
                path="/organization"
                element={<SettingsRedirect to="/settings#naming" />}
              />
              <Route
                path="/lists"
                element={<Lists canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/lists/:id"
                element={<Lists canEdit={auth.user.role !== "viewer"} />}
              />
              <Route
                path="/requests"
                element={
                  <RequestsPage
                    admin={auth.user.role === "admin"}
                    canRequest={auth.user.role !== "viewer"}
                  />
                }
              />
              <Route path="/activity" element={<LegacyActivityRedirect />} />
              <Route
                path="/accounts"
                element={<SettingsRedirect to="/settings#accounts" />}
              />
              <Route
                path="/library"
                element={
                  <MyLibrary
                    admin={auth.user.role === "admin"}
                    canEdit={auth.user.role !== "viewer"}
                  />
                }
              />
              <Route
                path="/review"
                element={<Navigate to="/library" replace />}
              />
              <Route
                path="/connections"
                element={<SettingsRedirect to="/settings#libraries" />}
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}

function SettingsRedirect({ to }: { to: string }) {
  const location = useLocation();
  const [path, hash] = to.split("#");
  return (
    <Navigate
      to={`${path}${location.search}${hash ? `#${hash}` : ""}`}
      replace
    />
  );
}

function LegacyActivityRedirect() {
  const location = useLocation();
  return (
    <SettingsRedirect
      to={
        location.hash === "#downloads"
          ? "/requests#downloads"
          : "/settings#logs"
      }
    />
  );
}
