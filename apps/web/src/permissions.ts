export type RequestMedium = "ebook" | "audio";

export function canRequestMedium(
  permissions: string[] = [],
  role = "",
  medium?: RequestMedium,
) {
  if (role === "viewer") return false;
  if (role === "admin") return true;
  const request = permissions.includes("request");
  const ebook = permissions.includes("request_ebook");
  const audio = permissions.includes("request_audio");
  const allowed = (slot: RequestMedium) => {
    if (slot === "ebook" ? ebook : audio) return true;
    if (!request) return false;
    return !(slot === "ebook" ? audio : ebook);
  };
  if (medium) return allowed(medium);
  return allowed("ebook") && allowed("audio");
}

export function canManageOwnRequests(permissions: string[] = [], role = "") {
  return (
    canRequestMedium(permissions, role, "ebook") ||
    canRequestMedium(permissions, role, "audio")
  );
}

export function canAutoDownload(
  permissions: string[] = [],
  role = "",
  medium?: RequestMedium,
) {
  if (role === "viewer") return false;
  if (role === "admin" || permissions.includes("auto_approve")) return true;
  if (medium === "ebook") return permissions.includes("auto_approve_ebook");
  if (medium === "audio") return permissions.includes("auto_approve_audio");
  return (
    permissions.includes("auto_approve_ebook") &&
    permissions.includes("auto_approve_audio")
  );
}

export function canStartDownload(
  permissions: string[] = [],
  role = "",
  medium?: RequestMedium,
) {
  return (
    canAutoDownload(permissions, role, medium) &&
    canRequestMedium(permissions, role, medium)
  );
}

export function canRequestAdvanced(permissions: string[] = [], role = "") {
  return role === "admin" || permissions.includes("request_advanced");
}
