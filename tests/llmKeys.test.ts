import test from "node:test";
import assert from "node:assert/strict";
import { hasAnyLlmKey, providerKeys, rotatedKeys } from "../lib/llmKeys";

test("providerKeys accepts multiple Groq keys and removes duplicates", () => {
  process.env.GROQ_API_KEYS = "key-a,key-b\nkey-a; key-c";
  process.env.GROQ_API_KEY = "key-d";
  assert.deepEqual(providerKeys("groq"), ["key-a", "key-b", "key-c", "key-d"]);
});

test("rotatedKeys changes the first OpenRouter key between calls", () => {
  process.env.OPENROUTER_API_KEYS = "a,b,c";
  delete process.env.OPENROUTER_API_KEY;
  const first = rotatedKeys("openrouter");
  const second = rotatedKeys("openrouter");
  assert.equal(first.length, 3);
  assert.equal(second.length, 3);
  assert.notEqual(first[0], second[0]);
  assert.deepEqual(new Set(first), new Set(second));
});

test("Gemini keys participate in configured-state detection", () => {
  delete process.env.GROQ_API_KEYS;
  delete process.env.GROQ_API_KEY;
  delete process.env.OPENROUTER_API_KEYS;
  delete process.env.OPENROUTER_API_KEY;
  process.env.GEMINI_API_KEYS = "gem-a,gem-b";
  assert.deepEqual(providerKeys("gemini"), ["gem-a", "gem-b"]);
  assert.equal(hasAnyLlmKey(), true);
});
