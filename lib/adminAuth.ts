import { createHash, timingSafeEqual } from "crypto";
import { NextRequest } from "next/server";
export const ADMIN_COOKIE="primehub_admin";
function password(){const value=process.env.ADMIN_PASSWORD;if(!value)throw new Error("ADMIN_PASSWORD is not configured");return value;}
export function adminToken(){return createHash("sha256").update(`primehub-admin:${password()}`).digest("hex");}
export function isAdmin(request:NextRequest){const actual=request.cookies.get(ADMIN_COOKIE)?.value;if(!actual)return false;const expected=adminToken();const a=Buffer.from(actual);const b=Buffer.from(expected);return a.length===b.length&&timingSafeEqual(a,b);}
