import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Auth = components["schemas"]["AuthView"];
export type Work = components["schemas"]["WorkView"];
export type BookList = components["schemas"]["ListView"];

let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
});
api.use({
  onResponse({ request, response }) {
    if (
      response.status === 401 &&
      !request.url.endsWith("/auth/login") &&
      !request.url.endsWith("/auth/me")
    ) {
      window.dispatchEvent(new Event("book:session-expired"));
    }
    return response;
  },
  onRequest({ request }) {
    if (!["GET", "HEAD"].includes(request.method) && csrf)
      request.headers.set("X-CSRF-Token", csrf);
    return request;
  },
});

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export function result<T>(value: {
  data?: T;
  error?: unknown;
  response: Response;
}): T {
  if (value.error || !value.response.ok) {
    const error = value.error as { detail?: unknown } | undefined;
    const detail =
      typeof error?.detail === "string"
        ? error.detail
        : "The request failed. Check your entries and try again.";
    throw new ApiError(detail, value.response.status);
  }
  return value.data as T;
}
