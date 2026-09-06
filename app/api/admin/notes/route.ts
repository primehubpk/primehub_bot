import {NextRequest,NextResponse} from "next/server";
import {isAdmin} from "@/lib/adminAuth";
import {ensureSchema,pool} from "@/lib/db";
export async function GET(request:NextRequest){if(!isAdmin(request))return NextResponse.json({error:"Unauthorized"},{status:401});await ensureSchema();const r=await pool.query("SELECT body,updated_at FROM admin_notes WHERE id=1");return NextResponse.json({note:r.rows[0]||{body:""}});}
export async function POST(request:NextRequest){if(!isAdmin(request))return NextResponse.json({error:"Unauthorized"},{status:401});await ensureSchema();const p=await request.json().catch(()=>({}));const body=String(p?.body||"").trim().slice(0,600);await pool.query("UPDATE admin_notes SET body=$1,updated_at=NOW() WHERE id=1",[body]);return NextResponse.json({ok:true,body});}
