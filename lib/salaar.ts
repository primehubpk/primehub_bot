import type { Product } from "./catalog";
import { hasAnyLlmKey, rotatedKeys } from "./llmKeys";

export const CONFIG_ERROR =
  "Salaar abhi configure nahi hua. Admin ko LLM API key add karni hogi — app chalti rahe gi.";
export const WHATSAPP_FALLBACK =
  "Agar baat clear na ho rahi ho to 03238878009 par WhatsApp text kar dein, hum help kar dein ge.";

const defaultReply = "Ji, batayein kis cheez mein help chahiye?";

function promptText(customerMessage: string, productText: string) {
  return `Customer: ${customerMessage}\nCatalog tool results:\n${productText}`;
}

async function tryOpenAiCompatible(
  endpoint: string,
  key: string,
  model: string,
  system: string,
  customerMessage: string,
  productText: string,
  extraHeaders: Record<string, string> = {},
) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
      ...extraHeaders,
    },
    body: JSON.stringify({
      model,
      temperature: 0.4,
      max_tokens: 180,
      messages: [
        { role: "system", content: system },
        { role: "user", content: promptText(customerMessage, productText) },
      ],
    }),
  });
  if (!response.ok) throw new Error(`${endpoint} ${response.status}`);
  const data = await response.json();
  return (data?.choices?.[0]?.message?.content || defaultReply).trim();
}

async function tryGemini(key: string, system: string, customerMessage: string, productText: string) {
  const model = process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(key)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: [{ role: "user", parts: [{ text: promptText(customerMessage, productText) }] }],
        generationConfig: { temperature: 0.4, maxOutputTokens: 180 },
      }),
    },
  );
  if (!response.ok) throw new Error(`Gemini ${response.status}`);
  const data = await response.json();
  return (data?.candidates?.[0]?.content?.parts?.[0]?.text || defaultReply).trim();
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

  for (const key of rotatedKeys("groq")) {
    try {
      return {
        text: await tryOpenAiCompatible(
          "https://api.groq.com/openai/v1/chat/completions",
          key,
          process.env.GROQ_MODEL || "llama-3.3-70b-versatile",
          system,
          customerMessage,
          productText,
        ),
        configured: true,
      };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "Groq error");
    }
  }

  for (const key of rotatedKeys("openrouter")) {
    try {
      const headers: Record<string, string> = {};
      if (process.env.NEXT_PUBLIC_APP_URL) headers["HTTP-Referer"] = process.env.NEXT_PUBLIC_APP_URL;
      headers["X-Title"] = "PrimeHubMaal Salaar";
      return {
        text: await tryOpenAiCompatible(
          "https://openrouter.ai/api/v1/chat/completions",
          key,
          process.env.OPENROUTER_MODEL || "google/gemini-2.5-flash",
          system,
          customerMessage,
          productText,
          headers,
        ),
        configured: true,
      };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "OpenRouter error");
    }
  }

  for (const key of rotatedKeys("gemini")) {
    try {
      return { text: await tryGemini(key, system, customerMessage, productText), configured: true };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "Gemini error");
    }
  }

  console.error("Salaar LLM providers exhausted", errors.join(" | "));
  return {
    text: "Salaar ka reply service abhi available nahi. Thori dair baad try karein. " + WHATSAPP_FALLBACK,
    configured: true,
  };
}
