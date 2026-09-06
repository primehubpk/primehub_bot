import { Pool, PoolClient } from "pg";

const globalForDb = globalThis as unknown as { primeHubPool?: Pool; schemaReady?: Promise<void> };
function connectionString(){ const value=process.env.DATABASE_URL; if(!value) throw new Error("DATABASE_URL is not configured"); return value; }
function sslConfig(){if(process.env.DATABASE_SSL==="false")return undefined;if(process.env.DATABASE_SSL==="true")return{rejectUnauthorized:false};return process.env.NODE_ENV === "production" ? { rejectUnauthorized: false } : undefined;}
export const pool = globalForDb.primeHubPool ?? new Pool({ connectionString: connectionString(), ssl: sslConfig() });
if(process.env.NODE_ENV !== "production") globalForDb.primeHubPool = pool;
async function createSchema(client:PoolClient){
  await client.query(`
    CREATE TABLE IF NOT EXISTS sessions(id UUID PRIMARY KEY,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
    CREATE TABLE IF NOT EXISTS conversations(id UUID PRIMARY KEY,session_id UUID NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,status TEXT NOT NULL DEFAULT 'AUTO',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
    CREATE TABLE IF NOT EXISTS messages(id BIGSERIAL PRIMARY KEY,conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,role TEXT NOT NULL CHECK(role IN ('customer','admin','salaar-stub')),body TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS shown_product_ids TEXT[] NOT NULL DEFAULT '{}';
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS cart JSONB NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS hold_until TIMESTAMPTZ;
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS hard_mute BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS need_you BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE conversations ADD COLUMN IF NOT EXISTS reseller_collecting BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;
    CREATE TABLE IF NOT EXISTS orders(id UUID PRIMARY KEY,conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,status TEXT NOT NULL DEFAULT 'New order',cart_snapshot JSONB NOT NULL,full_name TEXT NOT NULL,phone TEXT NOT NULL,city TEXT NOT NULL,address TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',total INTEGER NOT NULL,advance_pending INTEGER NOT NULL DEFAULT 300,remaining INTEGER NOT NULL,email_configured BOOLEAN NOT NULL DEFAULT FALSE,email_sent BOOLEAN NOT NULL DEFAULT FALSE,email_error TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),completed_at TIMESTAMPTZ);
    CREATE TABLE IF NOT EXISTS admin_notes(id SMALLINT PRIMARY KEY DEFAULT 1 CHECK(id=1),body TEXT NOT NULL DEFAULT '',updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
    INSERT INTO admin_notes(id,body) VALUES(1,'') ON CONFLICT(id) DO NOTHING;
    CREATE TABLE IF NOT EXISTS reseller_requests(id UUID PRIMARY KEY,conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Pending reseller',temp_password TEXT,account_email_sent BOOLEAN NOT NULL DEFAULT FALSE,email_error TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),approved_at TIMESTAMPTZ);
    CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id ON messages(conversation_id,id);
    CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_orders_conversation_created ON orders(conversation_id,created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_reseller_status_created ON reseller_requests(status,created_at DESC);
  `);
}
export async function ensureSchema(){ if(!globalForDb.schemaReady){ globalForDb.schemaReady=(async()=>{const client=await pool.connect();try{await createSchema(client)}finally{client.release()}})().catch(e=>{globalForDb.schemaReady=undefined;throw e}); } await globalForDb.schemaReady; }
