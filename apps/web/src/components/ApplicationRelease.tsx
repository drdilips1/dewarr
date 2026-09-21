import { useQuery } from "@tanstack/react-query";
import { api, result } from "../api/client";

export function ApplicationRelease() {
  const { data, isError } = useQuery({
    queryKey: ["application-release"],
    queryFn: async () => result(await api.GET("/api/application/release")),
    staleTime: 60 * 60 * 1000,
    refetchInterval: 60 * 60 * 1000,
    retry: false,
  });
  if (!data?.installed_version)
    return (
      <footer className="application-release">
        <small>{isError ? "Version unavailable" : "Checking version…"}</small>
      </footer>
    );
  const label = data.installed_version.startsWith("v")
    ? data.installed_version
    : `v${data.installed_version}`;
  return (
    <footer
      className="application-release"
      role="group"
      aria-label="Application version"
    >
      {data.installed_url ? (
        <a
          className="installed-version"
          href={data.installed_url}
          target="_blank"
          rel="noreferrer"
          title="Installed version release on GitHub"
        >
          {label}
        </a>
      ) : (
        <span className="installed-version">{label}</span>
      )}
      {data.update_available && data.release_url ? (
        <a
          className="release-update"
          href={data.release_url}
          target="_blank"
          rel="noreferrer"
          title={`Version ${data.latest_version} is available on GitHub`}
        >
          Update
        </a>
      ) : (
        <small>
          {data.status === "checked"
            ? !/^v?\d+\.\d+\.\d+(?:\+[\w.-]+)?$/.test(data.installed_version)
              ? "Unreleased build"
              : "Up to date"
            : data.status === "unconfigured"
              ? "Release tracking not configured"
              : data.status === "no-release"
                ? "No releases yet"
                : "Update check unavailable"}
        </small>
      )}
    </footer>
  );
}
