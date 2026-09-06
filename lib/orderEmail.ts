import nodemailer from "nodemailer";
import type {CustomerDetails,OrderCartItem} from "@/lib/order";

export type EmailResult={configured:boolean;sent:boolean;error?:string};
function esc(value:string){return value.replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[ch]||ch));}
function config(){const host=process.env.SMTP_HOST;const user=process.env.SMTP_USER;const pass=process.env.SMTP_PASS;const to=process.env.OPS_EMAIL;const from=process.env.SMTP_FROM||user;const port=Number(process.env.SMTP_PORT||587);if(!host||!user||!pass||!to||!from)return null;return{host,user,pass,to,from,port};}
export function isOpsEmailConfigured(){return Boolean(config());}
export async function sendOpsOrderEmail(input:{orderId:string;details:CustomerDetails;cart:OrderCartItem[];total:number;advancePending:number;remaining:number}):Promise<EmailResult>{
 const cfg=config();if(!cfg)return{configured:false,sent:false,error:"email not configured"};
 const transporter=nodemailer.createTransport({host:cfg.host,port:cfg.port,secure:cfg.port===465,auth:{user:cfg.user,pass:cfg.pass}});
 const items=input.cart.map((item,index)=>`<div style="margin:0 0 24px"><div style="font-weight:700;margin-bottom:8px">Item ${index+1}: ${esc(item.name)}</div><img src="${esc(item.image)}" alt="${esc(item.name)}" style="display:block;max-width:420px;width:100%;height:auto;border-radius:12px;margin-bottom:8px"/><div>Size: ${esc(item.size||"N/A")}</div><div>Qty: ${item.qty}</div><div>Color: ${esc(item.color||"As shown")}</div><div>Price: Rs ${item.price}</div></div>`).join("");
 const html=`<h2>New order</h2><p><strong>Order:</strong> ${esc(input.orderId)}</p>${items}<hr/><p><strong>Name:</strong> ${esc(input.details.fullName)}</p><p><strong>Phone:</strong> ${esc(input.details.phone)}</p><p><strong>City:</strong> ${esc(input.details.city)}</p><p><strong>Full address:</strong> ${esc(input.details.address)}</p><p><strong>Notes:</strong> ${esc(input.details.notes||"-")}</p><p><strong>Total:</strong> Rs ${input.total}</p><p><strong>300 pending:</strong> Rs ${input.advancePending}</p><p><strong>Remaining:</strong> Rs ${input.remaining}</p><p><strong>Label:</strong> New order</p>`;
 try{await transporter.sendMail({from:cfg.from,to:cfg.to,subject:`New order · ${input.orderId}`,html,text:`New order ${input.orderId}\n${input.details.fullName}\n${input.details.phone}\n${input.details.city}\n${input.details.address}\nTotal Rs ${input.total}\n300 pending Rs ${input.advancePending}\nRemaining Rs ${input.remaining}`});return{configured:true,sent:true};}catch(error){console.error("Ops email failed",error);return{configured:true,sent:false,error:error instanceof Error?error.message:"email send failed"};}
}
