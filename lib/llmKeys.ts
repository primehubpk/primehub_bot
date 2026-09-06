type Provider = "openai" | "anthropic";

const cursors: Record<Provider, number> = { openai: 0, anthropic: 0 };

function splitKeys(raw?: string) {
  return (raw || "")
    .split(/[\n,;]+/)
    .map((key) => key.trim())
    .filter(Boolean);
}

export function providerKeys(provider: Provider) {
  const plural = provider === "openai" ? process.env.OPENAI_API_KEYS : process.env.ANTHROPIC_API_KEYS;
  const single = provider === "openai" ? process.env.OPENAI_API_KEY : process.env.ANTHROPIC_API_KEY;
  const keys = [...splitKeys(plural), ...splitKeys(single)];
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
  return providerKeys("openai").length > 0 || providerKeys("anthropic").length > 0;
}
