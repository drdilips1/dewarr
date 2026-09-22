import assert from "node:assert/strict";
import { test } from "node:test";
import {
  nextRequestOffset,
  requestCountLabel,
  requestFilter,
} from "./requestFilters.ts";

test("a status query wins over a legacy hash", () => {
  assert.equal(requestFilter("#downloads", "library"), "library");
  assert.equal(requestFilter("#approvals", "declined"), "declined");
});

test("a legacy hash still selects the filter when no status query is present", () => {
  assert.equal(requestFilter("#downloads", null), "downloading");
  assert.equal(requestFilter("#approvals", null), "pending");
  assert.equal(requestFilter("#reviews", null), "review");
  assert.equal(requestFilter("#review", ""), "review");
});

test("an unknown status falls through to the hash, then to all", () => {
  assert.equal(requestFilter("#downloads", "nope"), "downloading");
  assert.equal(requestFilter("", null), "all");
});

test("a bounded filter resumes from the candidate cursor", () => {
  const page = { items: [], total: 80, next_offset: 40, total_bounded: true };
  assert.equal(nextRequestOffset(page, [page], 0), 40);
  assert.equal(
    nextRequestOffset(
      {
        items: [{ id: "a" }],
        total: 80,
        next_offset: null,
        total_bounded: true,
      },
      [{ items: [{ id: "a" }] }],
      40,
    ),
    undefined,
  );
});

test("an exact page still advances by the number of visible rows", () => {
  const page = { items: [{}], total: 3 };
  assert.equal(nextRequestOffset(page, [page]), 1);
  assert.equal(
    nextRequestOffset({ items: [{}, {}], total: 2 }, [{ items: [{}, {}] }]),
    undefined,
  );
});

test("a bounded count stays open until the last page", () => {
  assert.equal(requestCountLabel(10, 80, true, true), "10+ requests");
  assert.equal(requestCountLabel(12, 80, true, false), "12 requests");
  assert.equal(requestCountLabel(1, 1, false, false), "1 request");
});
