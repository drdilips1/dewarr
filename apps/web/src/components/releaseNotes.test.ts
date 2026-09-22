import assert from "node:assert/strict";
import { test } from "node:test";
import { releaseIsNewer, releaseNoteBlocks } from "./releaseNotes.ts";

test("release notes keep headings, lists, code, and safe links", () => {
  const blocks = releaseNoteBlocks(
    [
      "## Features",
      "",
      "Read the [guide](https://example.com/guide) and ignore [bad](javascript:alert(1)).",
      "",
      "- Reading lists",
      "- **Automatic** downloads",
      "",
      "```",
      "docker compose up -d",
      "```",
    ].join("\n"),
  );
  assert.deepEqual(blocks[0], {
    type: "heading",
    level: 2,
    inlines: [{ type: "text", value: "Features" }],
  });
  assert.equal(blocks[1].type, "paragraph");
  assert.deepEqual(
    blocks[1].type === "paragraph" ? blocks[1].inlines[1] : null,
    {
      type: "link",
      text: "guide",
      href: "https://example.com/guide",
    },
  );
  assert.equal(
    blocks[1].type === "paragraph" ? blocks[1].inlines.at(-1)?.type : null,
    "text",
  );
  assert.deepEqual(blocks[2], {
    type: "list",
    items: [
      [{ type: "text", value: "Reading lists" }],
      [
        { type: "strong", value: "Automatic" },
        { type: "text", value: " downloads" },
      ],
    ],
  });
  assert.deepEqual(blocks[3], {
    type: "code",
    value: "docker compose up -d",
  });
});

test("only a higher stable version counts as newer", () => {
  assert.equal(releaseIsNewer("v1.9.0", "v1.10.0"), true);
  assert.equal(releaseIsNewer("1.10.0", "v1.10.0"), false);
  assert.equal(releaseIsNewer("v2.0.0", "v1.10.0"), false);
  assert.equal(releaseIsNewer("1.0.0-dev", "v1.10.0"), false);
});
