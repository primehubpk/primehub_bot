# PrimeHub Bot — Phase 4

Standalone repo: `primehubpk/primehub_bot`. Phase 4 keeps Phase 1–3 chat, Salaar, catalog/cart, wait/continue, Ready/Rs 300, ops email, WhatsApp link, and Mark Complete. The `primhubpk`/PrimeHub website repo is not edited or deployed here.

## Phase 4 included
- Short PrimeHubMaal knowledge for Prime Skill, Reseller Club, shipping, returns, and retail vs wholesale.
- Prime Skill / Reseller links are configurable through `PRIME_SKILL_URL` and `RESELLER_CLUB_URL`; mock relative paths are used until Phase 5.
- `/admin/phase4` has a 2–3 line `What's new` note. Salaar reads the latest note before LLM replies and can answer latest-feature questions from it.
- Reseller signup can start from chat (`reseller pe signup kar do`). Salaar collects `Name | email | phone`, saves `Pending reseller`, and waits for admin approval.
- `/admin/phase4` shows the reseller queue. Approve creates a mock account/temp password and emails login details through the existing SMTP config when available. Chat says `Email check kar lo` when email was sent and never prints the password there.
- If SMTP is missing/broken, approval does not crash; admin gets a clear email warning.
- Angry/payment-stuck/reseller-confused/human-needed messages mark the conversation `NEED YOU`, offer WhatsApp text at `03238878009`, and keep replies short. The sidebar shows the `NEED YOU` badge. An admin reply clears it and still triggers the existing one-hour SOFT HOLD.

## Environment
```env
DATABASE_URL=
DATABASE_SSL=
ADMIN_PASSWORD=
NEXT_PUBLIC_APP_URL=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-haiku-latest
OPS_EMAIL=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=
PRIME_SKILL_URL=/prime-skill
RESELLER_CLUB_URL=/reseller-club
```

## Run / verify
```bash
npm install
npm run lint
npm run typecheck
npm test
npm run build
npm run dev
```

Public: `http://localhost:3000`  
Admin inbox: `http://localhost:3000/admin`  
Knowledge/reseller admin: `http://localhost:3000/admin/phase4`

## Phase 4 verify
- [ ] Ask `Prime Skill kya hai?` → short useful answer.
- [ ] Ask `reseller pe signup kar do` → send `Name | email | phone` → admin queue shows `Pending reseller`.
- [ ] Approve reseller → SMTP configured: login email sent and chat says `Email check kar lo`; SMTP missing: approval remains saved and admin sees warning.
- [ ] Trigger `samajh nahi aya payment` → chat offers `03238878009` and admin sidebar shows `NEED YOU`.
- [ ] Add 2 products and run Phase 3 Ready flow → order still saves and WhatsApp link still works.
- [ ] GitHub Phase 4 CI is green: npm ci, lint, typecheck, unit tests, production build, PostgreSQL runtime smoke test.

## Deploy rule
Do not require Railway and do not create a new paid Vercel project. Use an existing standalone preview only if one already exists. Production remains one VPS later, one codebase, many bots. Phase 5 website embed/VPS cutover is not started here.
