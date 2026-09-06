import {NextRequest,NextResponse} from "next/server";
import {isAdmin} from "@/lib/adminAuth";
import {ensureSchema,pool} from "@/lib/db";
import {searchCatalog} from "@/lib/catalog";
import {generateSalaarReply} from "@/lib/salaar";

async function answerLatestPending(conversationId:string){
  const state=(await pool.query("SELECT shown_product_ids FROM conversations WHERE id=$1",[conversationId])).rows[0];
  const pending=(await pool.query(`SELECT m.id,m.body FROM messages m WHERE m.conversation_id=$1 AND m.role='customer' AND NOT EXISTS(SELECT 1 FROM messages newer WHERE newer.conversation_id=m.conversation_id AND newer.id>m.id AND newer.role='salaar-stub') ORDER BY m.id DESC LIMIT 1`,[conversationId])).rows[0];
  if(!pending)return;
  const products=searchCatalog(pending.body,state?.shown_product_ids||[],3);
  const reply=await generateSalaarReply(pending.body,products);
  await pool.query("INSERT INTO messages(conversation_id,role,body,meta) VALUES($1,'salaar-stub',$2,$3::jsonb)",[conversationId,reply.text,JSON.stringify({products})]);
  if(products.length)await pool.query("UPDATE conversations SET shown_product_ids=array_cat(shown_product_ids,$2::text[]),updated_at=NOW() WHERE id=$1",[conversationId,products.map(p=>p.id)]);
}

export async function POST(request:NextRequest){
  if(!isAdmin(request))return NextResponse.json({error:"Unauthorized"},{status:401});
  await ensureSchema();
  const payload=await request.json().catch(()=>({}));
  const id=typeof payload?.conversationId==="string"?payload.conversationId:"";
  const action=payload?.action;
  if(!id||!["wait","continue"].includes(action))return NextResponse.json({error:"Invalid control"},{status:400});
  if(action==="wait"){
    await pool.query("UPDATE conversations SET status='WAIT',hard_mute=TRUE,hold_until=NULL,updated_at=NOW() WHERE id=$1",[id]);
    return NextResponse.json({ok:true,status:"WAIT"});
  }
  await pool.query("UPDATE conversations SET status='AUTO',hard_mute=FALSE,hold_until=NULL,updated_at=NOW() WHERE id=$1",[id]);
  await answerLatestPending(id);
  return NextResponse.json({ok:true,status:"AUTO"});
}
