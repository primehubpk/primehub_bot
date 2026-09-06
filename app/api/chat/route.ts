import { randomUUID } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { ensureSchema, pool } from "@/lib/db";
import { searchCatalog } from "@/lib/catalog";
import { generateSalaarReply } from "@/lib/salaar";

const SESSION_COOKIE="primehub_session";
async function ensureConversation(request:NextRequest){await ensureSchema();let sessionId=request.cookies.get(SESSION_COOKIE)?.value;let createdCookie=false;if(!sessionId){sessionId=randomUUID();createdCookie=true;}let row=(await pool.query("SELECT id FROM conversations WHERE session_id=$1",[sessionId])).rows[0];if(!row){await pool.query("INSERT INTO sessions(id) VALUES($1) ON CONFLICT(id) DO UPDATE SET last_seen_at=NOW()",[sessionId]);const conversationId=randomUUID();row=(await pool.query("INSERT INTO conversations(id,session_id) VALUES($1,$2) ON CONFLICT(session_id) DO UPDATE SET updated_at=NOW() RETURNING id",[conversationId,sessionId])).rows[0];}else{await pool.query("UPDATE sessions SET last_seen_at=NOW() WHERE id=$1",[sessionId]);}return{sessionId,conversationId:row.id as string,createdCookie};}
function withCookie(response:NextResponse,sessionId:string,shouldSet:boolean){if(shouldSet)response.cookies.set(SESSION_COOKIE,sessionId,{httpOnly:true,sameSite:"lax",secure:process.env.NODE_ENV==="production",path:"/",maxAge:31536000});return response;}

async function maybeResume(conversationId:string){
 const c=(await pool.query("SELECT status,hold_until,hard_mute,shown_product_ids FROM conversations WHERE id=$1",[conversationId])).rows[0];
 if(!c||c.status!=="WAIT"||c.hard_mute||!c.hold_until||new Date(c.hold_until)>new Date())return;
 const pending=(await pool.query(`SELECT m.id,m.body FROM messages m WHERE m.conversation_id=$1 AND m.role='customer' AND NOT EXISTS(SELECT 1 FROM messages newer WHERE newer.conversation_id=m.conversation_id AND newer.id>m.id AND newer.role='salaar-stub') ORDER BY m.id DESC LIMIT 1`,[conversationId])).rows[0];
 await pool.query("UPDATE conversations SET status='AUTO',hold_until=NULL WHERE id=$1",[conversationId]);
 if(!pending)return;
 const products=searchCatalog(pending.body,c.shown_product_ids||[],3);
 const reply=await generateSalaarReply(pending.body,products);
 await pool.query("INSERT INTO messages(conversation_id,role,body,meta) VALUES($1,'salaar-stub',$2,$3::jsonb)",[conversationId,reply.text,JSON.stringify({products})]);
 if(products.length)await pool.query("UPDATE conversations SET shown_product_ids=array_cat(shown_product_ids,$2::text[]),updated_at=NOW() WHERE id=$1",[conversationId,products.map(p=>p.id)]);
}

export async function GET(request:NextRequest){try{const{sessionId,conversationId,createdCookie}=await ensureConversation(request);await maybeResume(conversationId);const result=await pool.query("SELECT id,role,body,meta,created_at FROM messages WHERE conversation_id=$1 ORDER BY id ASC",[conversationId]);const cart=(await pool.query("SELECT cart,status FROM conversations WHERE id=$1",[conversationId])).rows[0];return withCookie(NextResponse.json({conversationId,messages:result.rows,cart:cart?.cart||[],status:cart?.status||'AUTO'}),sessionId,createdCookie);}catch(e){console.error(e);return NextResponse.json({error:"Chat is temporarily unavailable"},{status:500});}}

export async function POST(request:NextRequest){try{const payload=await request.json();const body=typeof payload?.body==="string"?payload.body.trim():"";if(!body||body.length>2000)return NextResponse.json({error:"Message must be 1-2000 characters"},{status:400});const{sessionId,conversationId,createdCookie}=await ensureConversation(request);await pool.query("INSERT INTO messages(conversation_id,role,body) VALUES($1,'customer',$2)",[conversationId,body]);await pool.query("UPDATE conversations SET updated_at=NOW() WHERE id=$1",[conversationId]);const c=(await pool.query("SELECT status,hold_until,hard_mute,shown_product_ids FROM conversations WHERE id=$1",[conversationId])).rows[0];
 const waiting=c?.status==="WAIT"&&(c.hard_mute||!c.hold_until||new Date(c.hold_until)>new Date());
 if(!waiting){
   if(c?.status==="WAIT")await pool.query("UPDATE conversations SET status='AUTO',hold_until=NULL WHERE id=$1",[conversationId]);
   const asksForNew=/kuch aur|aur dikhao|more|another|different/i.test(body);
   if(asksForNew)await pool.query("UPDATE conversations SET shown_product_ids='{}'::text[] WHERE id=$1",[conversationId]);
   const shown=asksForNew?[]:(c?.shown_product_ids||[]);
   const products=searchCatalog(body,shown,3);
   const reply=await generateSalaarReply(body,products);
   await pool.query("INSERT INTO messages(conversation_id,role,body,meta) VALUES($1,'salaar-stub',$2,$3::jsonb)",[conversationId,reply.text,JSON.stringify({products})]);
   if(products.length)await pool.query("UPDATE conversations SET shown_product_ids=array_cat(shown_product_ids,$2::text[]),updated_at=NOW() WHERE id=$1",[conversationId,products.map(p=>p.id)]);
 }
 return withCookie(NextResponse.json({ok:true,waiting}),sessionId,createdCookie);}catch(e){console.error(e);return NextResponse.json({error:"Message could not be saved"},{status:500});}}
