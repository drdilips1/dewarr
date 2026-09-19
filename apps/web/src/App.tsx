import { lazy, Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  Library,
  List,
  LogOut,
  Search,
  Settings,
  Users,
} from "lucide-react";
import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { api, ApiError, result, setCsrf } from "./api/client";
import type { Auth } from "./api/client";
import { Loading, Notice } from "./components";

const Catalog = lazy(() => import("./pages/Catalog"));
const BookDetail = lazy(() => import("./pages/BookDetail"));
const Series = lazy(() => import("./pages/Series"));
const Lists = lazy(() => import("./pages/Lists"));
const ActivityPage = lazy(() => import("./pages/Activity"));
const Connections = lazy(() => import("./pages/Connections"));
const DownloadPreferences = lazy(() => import("./pages/DownloadPreferences"));
const Downloaders = lazy(() => import("./pages/Downloaders"));
const AudiobookBaySources = lazy(() => import("./pages/AudiobookBaySources"));
const ProwlarrSources = lazy(() => import("./pages/ProwlarrSources"));
const Sources = lazy(() => import("./pages/Sources"));
const SourceArtifact = lazy(() => import("./pages/SourceArtifact"));
const MyLibrary = lazy(() => import("./pages/MyLibrary"));
const Accounts = lazy(() => import("./pages/Accounts"));
const ProviderSearch = lazy(() => import("./pages/ProviderSearch"));
const Organization = lazy(() => import("./pages/Organization"));
const ImportReview = lazy(() => import("./pages/ImportReview"));
const Destinations = lazy(() => import("./pages/Destinations"));
const MetadataSettings = lazy(() => import("./pages/MetadataSettings"));

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
          <BookOpen size={30} />
          <span>Book Search</span>
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
  const [search, setSearch] = useState("");
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
    navigate("/?q=" + encodeURIComponent(search));
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <BookOpen size={27} />
          <span>Book Search</span>
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
          <NavLink to="/" end>
            <Library size={19} />
            Catalog
          </NavLink>
          <NavLink to="/library">
            <BookOpen size={19} />
            My Library
          </NavLink>
          <NavLink to="/search">
            <Search size={19} />
            Search books
          </NavLink>
          <NavLink to="/sources">
            <Search size={19} />
            Sources
          </NavLink>
          <NavLink to="/metadata">
            <Settings size={19} />
            Metadata
          </NavLink>
          {auth.user.role === "admin" && (
            <NavLink to="/connections">
              <Settings size={19} />
              Connections
            </NavLink>
          )}
          {auth.user.role === "admin" && (
            <NavLink to="/organization">
              <Settings size={19} />
              Organization
            </NavLink>
          )}
          <NavLink to="/lists">
            <List size={19} />
            Lists
          </NavLink>
          <NavLink to="/activity">
            <Activity size={19} />
            Activity
          </NavLink>
          {auth.user.role === "admin" ? (
            <NavLink to="/accounts">
              <Users size={19} />
              Accounts
            </NavLink>
          ) : null}
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
      </aside>
      <div className="workspace">
        <header className="topbar">
          <form className="search" onSubmit={searchSubmit}>
            <Search size={18} aria-hidden="true" />
            <input
              aria-label="Search your catalog"
              placeholder="Search books or authors"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button type="submit">Search</button>
          </form>
          <span className="quiet-label">Your reading, organized.</span>
        </header>
        <main id="main" className="main-content">
          <Notice error={logout.error} />
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route
                path="/download-preferences"
                element={
                  auth.user.role !== "viewer" ? (
                    <DownloadPreferences admin={auth.user.role === "admin"} />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route
                path="/"
                element={<Catalog canEdit={auth.user.role !== "viewer"} />}
              />
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
                element={
                  <MetadataSettings admin={auth.user.role === "admin"} />
                }
              />
              <Route
                path="/sources"
                element={
                  <Sources
                    admin={auth.user.role === "admin"}
                    canAcquire={auth.user.role !== "viewer"}
                  />
                }
              />
              <Route
                path="/sources/audiobookbay"
                element={
                  <AudiobookBaySources
                    admin={auth.user.role === "admin"}
                    canAcquire={auth.user.role !== "viewer"}
                  />
                }
              />
              <Route
                path="/sources/prowlarr"
                element={
                  <ProwlarrSources
                    admin={auth.user.role === "admin"}
                    canAcquire={auth.user.role !== "viewer"}
                  />
                }
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
                element={
                  auth.user.role === "admin" ? (
                    <Downloaders />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route
                path="/organization/destinations"
                element={
                  auth.user.role === "admin" ? (
                    <Destinations />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
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
                element={
                  auth.user.role === "admin" ? (
                    <Organization />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
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
                path="/activity"
                element={
                  <ActivityPage
                    admin={auth.user.role === "admin"}
                    canRequest={auth.user.role !== "viewer"}
                  />
                }
              />
              <Route
                path="/accounts"
                element={
                  auth.user.role === "admin" ? (
                    <Accounts />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route
                path="/library"
                element={<MyLibrary admin={auth.user.role === "admin"} />}
              />
              <Route
                path="/connections"
                element={
                  auth.user.role === "admin" ? (
                    <Connections />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
