import {randomUUID} from "crypto";
import {NextRequest,NextResponse} from "next/server";
import {ensureSchema,pool} from "@/lib/db";
import {cartTotal,cleanPhone,remainingAfterAdvance,validCustomer,whatsappOrderUrl,type CustomerDetails,type OrderCartItem} from "@/lib/order";
import {sendOpsOrderEmail} from "@/lib/orderEmail";

const COOKIE="primehub_session";
const ADVANCE=300;
export async function POST(request:NextRequest){
 try{
  await ensureSchema();
  const sessionId=request.cookies.get(COOKIE)?.value;
  if(!sessionId)return NextResponse.json({error:"Chat session not found"},{status:400});
  const payload=await request.json().catch(()=>({}));
  const details:CustomerDetails={fullName:typeof payload?.fullName==="string"?payload.fullName.trim():"",phone:cleanPhone(typeof payload?.phone==="string"?payload.phone:""),city:typeof payload?.city==="string"?payload.city.trim():"",address:typeof payload?.address==="string"?payload.address.trim():"",notes:typeof payload?.notes==="string"?payload.notes.trim().slice(0,1000):""};
  if(!validCustomer(details))return NextResponse.json({error:"Name, valid phone, city aur complete address required hain."},{status:400});
  const conversation=(await pool.query("SELECT id,cart FROM conversations WHERE session_id=$1",[sessionId])).rows[0];
  if(!conversation)return NextResponse.json({error:"Conversation not found"},{status:404});
  const cart=(Array.isArray(conversation.cart)?conversation.cart:[]) as OrderCartItem[];
  if(!cart.length)return NextResponse.json({error:"Cart empty hai."},{status:400});
  const total=cartTotal(cart);if(total<=0)return NextResponse.json({error:"Cart total invalid hai."},{status:400});
  const remaining=remainingAfterAdvance(total,ADVANCE);const orderId=randomUUID();
  await pool.query(`INSERT INTO orders(id,conversation_id,status,cart_snapshot,full_name,phone,city,address,notes,total,advance_pending,remaining,email_configured,email_sent) VALUES($1,$2,'New order',$3::jsonb,$4,$5,$6,$7,$8,$9,$10,$11,FALSE,FALSE)`,[orderId,conversation.id,JSON.stringify(cart),details.fullName,details.phone,details.city,details.address,details.notes,total,ADVANCE,remaining]);
  const email=await sendOpsOrderEmail({orderId,details,cart,total,advancePending:ADVANCE,remaining});
  await pool.query("UPDATE orders SET email_configured=$2,email_sent=$3,email_error=$4 WHERE id=$1",[orderId,email.configured,email.sent,email.error||null]);
  await pool.query("UPDATE conversations SET updated_at=NOW() WHERE id=$1",[conversation.id]);
  const whatsappUrl=whatsappOrderUrl(orderId,details,cart,total);
  return NextResponse.json({ok:true,orderId,status:"New order",total,advancePending:ADVANCE,remaining,whatsappUrl,emailConfigured:email.configured,emailSent:email.sent,emailWarning:email.sent?null:(email.error||"email not configured")});
 }catch(error){console.error(error);return NextResponse.json({error:"Order save nahi ho saka. Dobara try karein."},{status:500});}
}
