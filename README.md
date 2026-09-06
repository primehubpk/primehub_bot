# PrimeHub Bot — Phase 1

Phase 1 adds a standalone PrimeHubMaal customer chat shell and human admin inbox inside `primehubpk/primehub_bot` only.

## Included
- Bottom-right `Need help?` widget with Salaar placeholder avatar.
- Header: `Salaar · PrimeHubMaal`.
- Guest messages persisted in PostgreSQL using a long-lived HTTP-only session cookie.
- Stub reply after customer messages.
- `/admin` password login using `ADMIN_PASSWORD`.
- `Admin — Salaar inbox` sidebar/thread UI with manual admin replies.
- Customer/admin polling every 2 seconds.
- Responsive layout for mobile.
- Conversation `status` defaults to `AUTO` for a later phase.

## Out of scope for Phase 1
No LLM, product catalog, cart, Rs 300 logic, Ready button, email, `wa.me`, WhatsApp Cloud API, Prime Skill, Reseller Club, or PrimeHub website deployment/editing.

## Environment
Copy `.env.example` to `.env.local` and set:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
ADMIN_PASSWORD=choose-a-strong-password
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

## Run locally
```bash
npm install
npm run typecheck
npm run build
npm run dev
```

Public page: `http://localhost:3000`
Admin inbox: `http://localhost:3000/admin`

The app creates the Phase 1 tables automatically on the first chat/admin API request. `db/schema.sql` is also included.

## Railway / VPS
Attach PostgreSQL, set `DATABASE_URL`, `ADMIN_PASSWORD`, and `NEXT_PUBLIC_APP_URL`, then run:

```bash
npm install
npm run build
npm start
```

## Phase 1 success check
1. Send two public messages and refresh; both remain.
2. Login to `/admin`, open the conversation, reply as admin.
3. Customer sees the admin reply without refreshing, within about 2 seconds.
4. Widget and admin inbox remain usable on mobile width.

## Repository isolation
The existing Python bot code remains in this repository and is not replaced by the Phase 1 web shell. The PrimeHub website repository is not cloned, edited, or deployed in Phase 1. Website embedding is reserved for Phase 5.
