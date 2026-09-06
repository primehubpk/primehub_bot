import test from "node:test";
import assert from "node:assert/strict";
import { providerKeys, rotatedKeys } from "../lib/llmKeys";

test("providerKeys accepts multiple keys and removes duplicates", () => {
  process.env.OPENAI_API_KEYS = "key-a,key-b\nkey-a; key-c";
  process.env.OPENAI_API_KEY = "key-d";
  assert.deepEqual(providerKeys("openai"), ["key-a", "key-b", "key-c", "key-d"]);
});

test("rotatedKeys changes the first key between calls", () => {
  process.env.ANTHROPIC_API_KEYS = "a,b,c";
  delete process.env.ANTHROPIC_API_KEY;
  const first = rotatedKeys("anthropic");
  const second = rotatedKeys("anthropic");
  assert.equal(first.length, 3);
  assert.equal(second.length, 3);
  assert.notEqual(first[0], second[0]);
  assert.deepEqual(new Set(first), new Set(second));
});
