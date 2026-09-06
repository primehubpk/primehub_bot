import type { Product } from "./catalog";
import { hasAnyLlmKey, rotatedKeys } from "./llmKeys";

export const CONFIG_ERROR =
  "Salaar abhi configure nahi hua. Admin ko LLM API key add karni hogi — app chalti rahe gi.";
export const WHATSAPP_FALLBACK =
  "Agar baat clear na ho rahi ho to 03238878009 par WhatsApp text kar dein, hum help kar dein ge.";

const defaultReply = "Ji, batayein kis cheez mein help chahiye?";

async function tryOpenAi(key: string, system: string, customerMessage: string, productText: string) {
  const response = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || "gpt-4.1-mini",
      temperature: 0.4,
      max_tokens: 180,
      messages: [
        { role: "system", content: system },
        { role: "user", content: `Customer: ${customerMessage}\nCatalog tool results:\n${productText}` },
      ],
    }),
  });
  if (!response.ok) throw new Error(`OpenAI ${response.status}`);
  const data = await response.json();
  return (data?.choices?.[0]?.message?.content || defaultReply).trim();
}

async function tryAnthropic(key: string, system: string, customerMessage: string, productText: string) {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: process.env.ANTHROPIC_MODEL || "claude-3-5-haiku-latest",
      max_tokens: 180,
      temperature: 0.4,
      system,
      messages: [
        { role: "user", content: `Customer: ${customerMessage}\nCatalog tool results:\n${productText}` },
      ],
    }),
  });
  if (!response.ok) throw new Error(`Anthropic ${response.status}`);
  const data = await response.json();
  return (data?.content?.[0]?.text || defaultReply).trim();
}

export async function generateSalaarReply(customerMessage: string, products: Product[], adminNotes = "") {
  if (!hasAnyLlmKey()) return { text: CONFIG_ERROR, configured: false };

  const productText = products.length
    ? products
        .map(
          (product) =>
            `${product.id}: ${product.name}, retail Rs ${product.retailPrice}, wholesale Rs ${product.wholesalePrice}, sizes ${product.sizes.join(", ")}`,
        )
        .join("\n")
    : "No catalog matches.";
  const notes = adminNotes.trim()
    ? `Latest admin What's new notes (treat as current PrimeHubMaal truth): ${adminNotes.trim()}`
    : "No latest admin notes.";
  const system = `You are Salaar, salesman for PrimeHubMaal. Reply in short warm Roman Urdu/English with pyar, adab and ehtram. Keep reply about as long as customer's message. No menus, no essays, never say you are AI. If catalog products are supplied, mention at most 2-3 naturally and do not invent products/prices. Prime Skill is a guided skills/earning area. Reseller Club is for wholesale/reseller customers and signup needs team approval. Retail is normal customer pricing; wholesale is bulk/approved reseller pricing. If confused or low confidence, include this exact fallback: ${WHATSAPP_FALLBACK}\n${notes}`;

  const errors: string[] = [];

  for (const key of rotatedKeys("openai")) {
    try {
      return { text: await tryOpenAi(key, system, customerMessage, productText), configured: true };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "OpenAI error");
    }
  }

  for (const key of rotatedKeys("anthropic")) {
    try {
      return { text: await tryAnthropic(key, system, customerMessage, productText), configured: true };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "Anthropic error");
    }
  }

  console.error("Salaar LLM providers exhausted", errors.join(" | "));
  return {
    text: "Salaar ka reply service abhi available nahi. Thori dair baad try karein. " + WHATSAPP_FALLBACK,
    configured: true,
  };
}
