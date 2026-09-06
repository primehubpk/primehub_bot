export const WHATSAPP_NUMBER="03238878009";
export const KNOWLEDGE={
 primeSkill:"Prime Skill PrimeHubMaal ka guided earning/skills area hai. Start karne ke liye Prime Skill section open karein aur apni skill choose karein.",
 reseller:"Reseller Club wholesale/reseller customers ke liye hai — bulk ya resale ke liye better rates aur reseller benefits milte hain. Signup team approval ke baad activate hota hai.",
 shipping:"Shipping city aur parcel ke hisaab se confirm hoti hai. Order lock ke baad team final dispatch detail share karti hai.",
 returns:"Return/exchange item condition aur issue par depend karta hai. Problem ho to order details ke sath team ko jaldi contact karein.",
 pricing:"Retail normal single/customer buying ke liye hai; wholesale/reseller rates bulk ya approved reseller customers ke liye hotay hain."
};
export function knowledgeAnswer(message:string,notes:string){const q=message.toLowerCase();let text:string|null=null;let link:string|undefined;
 if(q.includes("prime skill")||q.includes("skill kya")){text=KNOWLEDGE.primeSkill;link=process.env.PRIME_SKILL_URL||"/prime-skill";}
 else if(q.includes("reseller club")||q.includes("wholesale kya")||q.includes("reseller kya")){text=KNOWLEDGE.reseller;link=process.env.RESELLER_CLUB_URL||"/reseller-club";}
 else if(q.includes("shipping")||q.includes("delivery")){text=KNOWLEDGE.shipping;}
 else if(q.includes("return")||q.includes("exchange")){text=KNOWLEDGE.returns;}
 else if(q.includes("wholesale")||q.includes("retail")){text=KNOWLEDGE.pricing;}
 else if((q.includes("what's new")||q.includes("whats new")||q.includes("new feature")||q.includes("naya"))&&notes.trim()){text=`Abhi latest: ${notes.trim()}`;}
 return text?{text,link}:null;}
export function wantsResellerSignup(message:string){const q=message.toLowerCase();return q.includes("reseller")&&(q.includes("signup")||q.includes("sign up")||q.includes("register")||q.includes("account bana"));}
export function needsHuman(message:string){const q=message.toLowerCase();return /(ghussa|gussa|angry|bakwas|fraud|payment.*(stuck|phas|problem|issue)|samajh nahi aya payment|reseller.*(confus|samajh nahi)|human|agent|need you)/i.test(q);}
