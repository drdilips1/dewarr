import type { components } from "../api/schema";
export type NamingProfile = components["schemas"]["NamingProfile"];
export type Medium = "audio" | "ebook";
export type NamingChoices = {
  author: boolean;
  series: boolean;
  sequence: boolean;
  year: boolean;
  version: boolean;
  language: boolean;
  publisher: boolean;
};
export const simpleChoices: NamingChoices = {
  author: true,
  series: false,
  sequence: false,
  year: false,
  version: false,
  language: false,
  publisher: false,
};
export const seriesChoices: NamingChoices = {
  ...simpleChoices,
  series: true,
  sequence: true,
};
export const detailedChoices: NamingChoices = {
  ...seriesChoices,
  year: true,
  version: true,
};
export function folderTemplate(medium: Medium, choices: NamingChoices) {
  return `${choices.author ? "{author}/" : ""}${choices.series ? "[{series}/]" : ""}${choices.sequence ? "[{sequence} - ]" : ""}${choices.year ? (medium === "audio" ? "[{recording_year} - ]" : "[{edition_year} - ]") : ""}{title}${choices.version ? (medium === "audio" ? "[ - {narrator}]" : "[ - {edition}]") : ""}${choices.language ? "[ - {language}]" : ""}${choices.publisher ? "[ - {publisher}]" : ""}`;
}
export function readChoices(
  template: string,
  medium: Medium,
): NamingChoices | null {
  const choices = {
    author: template.includes("{author}"),
    series: template.includes("{series}"),
    sequence: template.includes("{sequence}"),
    year: template.includes(
      medium === "audio" ? "{recording_year}" : "{edition_year}",
    ),
    version: template.includes(medium === "audio" ? "{narrator}" : "{edition}"),
    language: template.includes("{language}"),
    publisher: template.includes("{publisher}"),
  };
  const segments = templateSegments(template);
  const tokens = segments.map((segment) => segment.match(/\{([^}]+)\}/g) || []);
  const supported = new Set([
    "{title}",
    "{author}",
    "{series}",
    "{sequence}",
    "{edition_year}",
    "{recording_year}",
    "{edition}",
    "{narrator}",
    "{language}",
    "{publisher}",
  ]);
  return tokens.every(
    (group) => group.length === 1 && supported.has(group[0]),
  ) && new Set(tokens.flat()).size === tokens.length
    ? choices
    : null;
}
// Sent to the same planner as real imports; these examples never enter the catalog.
export const namingExamples: components["schemas"]["ImportGroup"][] = (
  ["ebook", "audio"] as const
).map((medium, index) => ({
  id: `00000000-0000-0000-0000-00000000000${index + 1}`,
  work_id: "00000000-0000-0000-0000-000000000010",
  version_id: `00000000-0000-0000-0000-00000000002${index}`,
  medium,
  decision: "import" as const,
  full_content: true,
  metadata: {
    title: "Harry Potter and the Philosopher’s Stone",
    authors: ["J. K. Rowling"],
    series: "Harry Potter",
    sequence: "1",
    original_year: 1997,
    edition_year: 1997,
    recording_year: 1999,
    narrators: ["Stephen Fry"],
    edition: "First edition",
    publisher: "Bloomsbury",
    language: "English",
  },
  files: [
    {
      role: "media" as const,
      complete: true,
      path:
        medium === "audio"
          ? "Harry Potter/01 - The Boy Who Lived.mp3"
          : "Harry Potter.epub",
      ...(medium === "audio" ? { track: 1, disc: 1 } : {}),
    },
  ],
}));

// Keep punctuation and optional brackets attached when moving metadata segments.
export function templateSegments(template: string): string[] {
  const parts =
    template.match(/\[[^\]]*\]|[^\[\]{}]*\{[^}]+\}[^\[\]{}]*/g) || [];
  return parts.join("") === template && new Set(parts).size === parts.length
    ? parts
    : [template];
}
export function toggleSegment(
  template: string,
  medium: Medium,
  key: keyof NamingChoices,
) {
  const token =
    key === "year"
      ? medium === "audio"
        ? "recording_year"
        : "edition_year"
      : key === "version"
        ? medium === "audio"
          ? "narrator"
          : "edition"
        : key;
  const segments = templateSegments(template);
  if (segments.some((segment) => segment.includes(`{${token}}`)))
    return segments
      .filter((segment) => !segment.includes(`{${token}}`))
      .join("");
  const enabled = folderTemplate(medium, {
    ...simpleChoices,
    author: false,
    [key]: true,
  });
  const added = templateSegments(enabled).filter(
    (segment) => !segment.includes("{title}"),
  );
  const position = ["author", "series", "sequence", "year"].includes(key)
    ? segments.findIndex((segment) => segment.includes("{title}"))
    : segments.length;
  segments.splice(Math.max(0, position), 0, ...added);
  return segments.join("");
}
