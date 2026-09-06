# PrimeHub Bot — Phase 3

This repository is the standalone `primehubpk/primehub_bot` app. Phase 3 builds only on the Phase 1–2 chat shell, Salaar, catalog/cart, and admin inbox. The PrimeHub website repository is not cloned, edited, or deployed here.

## Phase 3 included
- Full cart summary before order lock.
- Collect full name, WhatsApp/contact number, city, complete address, and optional notes.
- Short Rs 300 advance script and large `Ready — order lock` button.
- READY saves a PostgreSQL order with label/status `New order`, immutable cart snapshot, customer details, total, Rs 300 pending, and remaining amount.
- Ops email through `OPS_EMAIL` + `SMTP_*` when configured. Each item is rendered separately: item image first, then size / qty / color / price underneath. No collage.
- Missing/broken SMTP never blocks order save. Customer still gets success + WhatsApp link; admin sees an email warning.
- One-tap customer `wa.me/923238878009` link with prefilled order name, city, items, total, and Rs 300 pending. This does not use WhatsApp Cloud API.
- Admin sidebar/thread shows `New order`; `Mark Complete` changes the latest order to `Complete` after ops manually sends the packing video.
- Phase 1–2 polling, Salaar AUTO/WAIT, catalog/cart and anti-repeat behavior remain unchanged.

## Out of scope
No WhatsApp Cloud API, automatic server-side WhatsApp sending, Reseller Club signup, Prime Skill crawl, 03490464541 API cards, Railway setup, or PrimeHub website embed/deployment.

## Environment
Copy `.env.example` to `.env.local` and set what you use:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
ADMIN_PASSWORD=choose-a-strong-password
NEXT_PUBLIC_APP_URL=http://localhost:3000
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
```

If SMTP values are blank, READY still saves the order and returns the WhatsApp link. Admin shows `email not configured`.

## Run / verify locally

```bash
npm install
npm run lint
npm run typecheck
npm test
npm run build
npm run dev
```

Public page: `http://localhost:3000`
Admin inbox: `http://localhost:3000/admin`

## CI
`.github/workflows/phase3-ci.yml` runs on Phase 3 pushes/PRs and executes dependency install, `npm ci`, lint, TypeScript checking, unit tests, and the production Next.js build.

## Phase 3 verify
- [ ] Add 2 different products to cart and confirm both appear separately in the cart summary.
- [ ] Fill full name, contact/WhatsApp number, city, complete address, and optional notes.
- [ ] Confirm the Rs 300 advance script is visible, then click `Ready — order lock`.
- [ ] Customer sees order success, total, Rs 300 pending, remaining, and one-tap `wa.me/923238878009` link.
- [ ] `/admin` shows `New order` for that conversation.
- [ ] Click `Mark Complete` and confirm the badge changes to `Complete`.
- [ ] With SMTP unset, order still saves and admin shows a clear email warning.
- [ ] With SMTP configured, ops email shows image 1 then item 1 details, image 2 then item 2 details — never a collage.
- [ ] GitHub Phase 3 CI is green: `npm ci`, lint, typecheck, tests, and `npm run build` all pass.

## Preview / deploy rule
Use the existing standalone `primehub_bot` Vercel deployment only if one is already attached to this repo. Do not create another paid host and do not point this code at the `primehub` website project. If no standalone preview is attached, verify locally plus GitHub Actions; production home remains the single VPS planned later.

As of this Phase 3 branch, no separate `primehub_bot` Vercel project URL is recorded in this repository, so there is no URL to invent here.
