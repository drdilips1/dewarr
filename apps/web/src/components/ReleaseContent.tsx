import type { ReactNode } from "react";

function readable(value: string) {
  if (!/<\/?(?:p|div|br|table|span|strong|pre|ul|li)\b/i.test(value))
    return value;
  const doc = new DOMParser().parseFromString(value, "text/html");
  doc
    .querySelectorAll("script,style,iframe,object")
    .forEach((node) => node.remove());
  doc.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
  doc
    .querySelectorAll("p,div,li,tr,h1,h2,h3,pre")
    .forEach((node) => node.append("\n"));
  return doc.body.textContent || "";
}
function inline(value: string): ReactNode {
  return value
    .split(/(\[b\].*?\[\/b\]|\[i\].*?\[\/i\])/gi)
    .map((part, index) => {
      if (/^\[b\]/i.test(part))
        return <strong key={index}>{part.slice(3, -4)}</strong>;
      if (/^\[i\]/i.test(part)) return <em key={index}>{part.slice(3, -4)}</em>;
      return part;
    });
}
export function ReleaseDescription({ text }: { text?: string | null }) {
  const lines = readable(text || "No description supplied.")
    .replace(
      /\[\/?(?:center|size|color|font|quote|url|img|list)(?:=[^\]]*)?\]/gi,
      "",
    )
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  return (
    <div className="release-prose">
      {lines.map((line, index) =>
        /^(?:[-•]|\[\*\])\s*/.test(line) ? (
          <p className="release-list-line" key={index}>
            • {inline(line.replace(/^(?:[-•]|\[\*\])\s*/, ""))}
          </p>
        ) : (
          <p key={index}>{inline(line)}</p>
        ),
      )}
    </div>
  );
}
export function ReleaseMediaInfo({ text }: { text?: string | null }) {
  if (!text) return <p className="muted">No media information supplied.</p>;
  let content = readable(text);
  try {
    const parsed: unknown = JSON.parse(content);
    if (parsed && typeof parsed === "object") {
      const lines: string[] = [];
      const walk = (value: unknown, key = "") => {
        if (value && typeof value === "object") {
          if (key && !/^\d+$/.test(key)) lines.push(`\n${key}`);
          Object.entries(value).forEach(([name, child]) => walk(child, name));
        } else if (value != null) lines.push(`${key}: ${String(value)}`);
      };
      walk(parsed);
      content = lines.join("\n");
    }
  } catch {
    /* Most sources supply the standard MediaInfo text report. */
  }
  const sections: {
    title: string;
    fields: { label: string; value: string }[];
    notes: string[];
  }[] = [];
  let section = {
    title: "Media information",
    fields: [] as { label: string; value: string }[],
    notes: [] as string[],
  };
  for (const raw of content.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const field = line.match(/^([^:]{1,90})\s*:\s*(.*)$/);
    if (field)
      section.fields.push({ label: field[1].trim(), value: field[2].trim() });
    else if (line.length < 90) {
      if (
        section.fields.length ||
        section.notes.length ||
        section.title !== "Media information"
      )
        sections.push(section);
      section = { title: line, fields: [], notes: [] };
    } else section.notes.push(line);
  }
  sections.push(section);
  return (
    <div className="release-media-sections">
      {sections.map((group, index) => (
        <section key={index}>
          <h3>{group.title}</h3>
          <dl>
            {group.fields.map((field, i) => (
              <div key={i}>
                <dt>{field.label}</dt>
                <dd>{field.value || "—"}</dd>
              </div>
            ))}
          </dl>
          {group.notes.map((note, i) => (
            <p key={i}>{note}</p>
          ))}
        </section>
      ))}
    </div>
  );
}
