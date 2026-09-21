import { useSyncExternalStore } from "react";

export type DisplayPreferences = {
  defaultShape: "square" | "portrait";
  audioShape: "square" | "portrait";
  ebookShape: "square" | "portrait";
};
export const displayDefaults: DisplayPreferences = {
  defaultShape: "portrait",
  audioShape: "portrait",
  ebookShape: "portrait",
};
const key = "book-search:display:v1";
let snapshot = displayDefaults;
function read() {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "{}");
    snapshot = { ...displayDefaults };
    for (const name of Object.keys(
      displayDefaults,
    ) as (keyof DisplayPreferences)[]) {
      const value = saved[name];
      if (
        name === "audioShape" ||
        name === "ebookShape" ||
        name === "defaultShape"
      ) {
        if (value === "square" || value === "portrait") snapshot[name] = value;
      }
    }
  } catch {
    snapshot = displayDefaults;
  }
}
read();
const listeners = new Set<() => void>();
window.addEventListener("storage", (event) => {
  if (event.key === key || event.key === null) {
    read();
    listeners.forEach((notify) => notify());
  }
});
function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}
export function useDisplayPreferences() {
  return useSyncExternalStore(subscribe, () => snapshot);
}
export function saveDisplayPreferences(value: DisplayPreferences) {
  localStorage.setItem(key, JSON.stringify(value));
  snapshot = value;
  listeners.forEach((notify) => notify());
}
