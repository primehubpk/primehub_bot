import { NextRequest, NextResponse } from "next/server";
import { isAdmin } from "@/lib/adminAuth";
import { ensureSchema, pool } from "@/lib/db";
export async function GET(request:NextRequest){if(!isAdmin(request))return NextResponse.json({error:"Unauthorized"},{status:401});await ensureSchema();const result=await pool.query(`SELECT c.id,c.session_id,c.status,c.updated_at,(SELECT body FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message,(SELECT created_at FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message_at FROM conversations c ORDER BY COALESCE((SELECT MAX(created_at) FROM messages m WHERE m.conversation_id=c.id),c.updated_at) DESC`);return NextResponse.json({conversations:result.rows});}
