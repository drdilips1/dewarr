import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { randomUUID } from "./randomUUID.ts";

const nativeRandomUUID = crypto.randomUUID.bind(crypto);
const nativeGetRandomValues = crypto.getRandomValues.bind(crypto);

afterEach(() => {
  define(crypto, "randomUUID", nativeRandomUUID);
  define(crypto, "getRandomValues", nativeGetRandomValues);
});

test("uses crypto.randomUUID when the browser provides it", () => {
  define(crypto, "randomUUID", () => "native-id");
  assert.equal(randomUUID(), "native-id");
});

test("builds an RFC 4122 UUID v4 when randomUUID is missing", () => {
  define(crypto, "randomUUID", undefined);
  define(crypto, "getRandomValues", (bytes: Uint8Array) => {
    bytes.fill(0);
    return bytes;
  });
  assert.equal(randomUUID(), "00000000-0000-4000-8000-000000000000");
});

test("keeps the random bits outside the version and variant fields", () => {
  define(crypto, "randomUUID", undefined);
  define(crypto, "getRandomValues", (bytes: Uint8Array) => {
    bytes.fill(0xff);
    return bytes;
  });
  assert.equal(randomUUID(), "ffffffff-ffff-4fff-bfff-ffffffffffff");
});

test("draws fallback ids from getRandomValues", () => {
  define(crypto, "randomUUID", undefined);
  const first = randomUUID();
  const second = randomUUID();
  assert.match(
    first,
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  assert.notEqual(first, second);
});

function define(target: object, key: string, value: unknown) {
  Object.defineProperty(target, key, {
    configurable: true,
    writable: true,
    value,
  });
}
