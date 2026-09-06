export type Provider = "groq" | "openrouter" | "gemini";

const cursors: Record<Provider, number> = { groq: 0, openrouter: 0, gemini: 0 };

function splitKeys(raw?: string) {
  return (raw || "")
    .split(/[\n,;]+/)
    .map((key) => key.trim())
    .filter(Boolean);
}

function envNames(provider: Provider) {
  if (provider === "groq") return ["GROQ_API_KEYS", "GROQ_API_KEY"] as const;
  if (provider === "openrouter") return ["OPENROUTER_API_KEYS", "OPENROUTER_API_KEY"] as const;
  return ["GEMINI_API_KEYS", "GEMINI_API_KEY"] as const;
}

export function providerKeys(provider: Provider) {
  const [pluralName, singleName] = envNames(provider);
  const keys = [...splitKeys(process.env[pluralName]), ...splitKeys(process.env[singleName])];
  return [...new Set(keys)];
}

export function rotatedKeys(provider: Provider) {
  const keys = providerKeys(provider);
  if (!keys.length) return [];
  const start = cursors[provider] % keys.length;
  cursors[provider] = (start + 1) % keys.length;
  return [...keys.slice(start), ...keys.slice(0, start)];
}

export function hasAnyLlmKey() {
  return providerKeys("groq").length > 0 || providerKeys("openrouter").length > 0 || providerKeys("gemini").length > 0;
}
