import type {Product} from "./catalog";

export const CONFIG_ERROR="Salaar abhi configure nahi hua. Admin ko LLM API key add karni hogi — app chalti rahe gi.";
export const WHATSAPP_FALLBACK="Agar baat clear na ho rahi ho to 03238878009 par WhatsApp text kar dein, hum help kar dein ge.";

export async function generateSalaarReply(customerMessage:string,products:Product[]){
 const openaiKey=process.env.OPENAI_API_KEY;
 const anthropicKey=process.env.ANTHROPIC_API_KEY;
 if(!openaiKey&&!anthropicKey)return {text:CONFIG_ERROR,configured:false};
 const productText=products.length?products.map(p=>`${p.id}: ${p.name}, retail Rs ${p.retailPrice}, wholesale Rs ${p.wholesalePrice}, sizes ${p.sizes.join(", ")}`).join("\n"):"No catalog matches.";
 const system=`You are Salaar, salesman for PrimeHubMaal. Reply in short warm Roman Urdu/English with pyar, adab and ehtram. Keep reply about as long as the customer's message. No menus, no essays, never say you are AI. If catalog products are supplied, mention at most 2-3 naturally and do not invent products/prices. If confused or low confidence, include this exact fallback: ${WHATSAPP_FALLBACK}`;
 try{
  if(openaiKey){
   const r=await fetch("https://api.openai.com/v1/chat/completions",{method:"POST",headers:{"Content-Type":"application/json",Authorization:`Bearer ${openaiKey}`},body:JSON.stringify({model:process.env.OPENAI_MODEL||"gpt-4.1-mini",temperature:0.4,max_tokens:180,messages:[{role:"system",content:system},{role:"user",content:`Customer: ${customerMessage}\nCatalog tool results:\n${productText}`}]})});
   if(!r.ok)throw new Error(`OpenAI ${r.status}`);
   const data=await r.json();
   return {text:(data?.choices?.[0]?.message?.content||"Ji, batayein kis cheez mein help chahiye?").trim(),configured:true};
  }
  const r=await fetch("https://api.anthropic.com/v1/messages",{method:"POST",headers:{"Content-Type":"application/json","x-api-key":anthropicKey!,"anthropic-version":"2023-06-01"},body:JSON.stringify({model:process.env.ANTHROPIC_MODEL||"claude-3-5-haiku-latest",max_tokens:180,temperature:0.4,system,messages:[{role:"user",content:`Customer: ${customerMessage}\nCatalog tool results:\n${productText}`}]})});
  if(!r.ok)throw new Error(`Anthropic ${r.status}`);
  const data=await r.json();
  return {text:(data?.content?.[0]?.text||"Ji, batayein kis cheez mein help chahiye?").trim(),configured:true};
 }catch(e){console.error("Salaar LLM error",e);return {text:"Salaar ka reply service abhi available nahi. Thori dair baad try karein. "+WHATSAPP_FALLBACK,configured:true};}
}
