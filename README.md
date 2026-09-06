# PrimeHub Bot — Phase 2

This repository is the standalone `primehubpk/primehub_bot` app. Phase 2 builds on the Phase 1 chat shell and admin inbox. The PrimeHub website repository is not cloned, edited, or deployed here.

## Phase 2 included
- Salaar salesman replies through OpenAI or Anthropic environment keys.
- Friendly in-chat configuration error when no LLM key is set; the app does not crash.
- Replaceable mock catalog tool with bangles and watches, photos, retail/wholesale prices, and sizes.
- Product cards with `Add to cart` and a per-session cart summary.
- `shown_product_ids` anti-repeat tracking per conversation.
- Admin reply = one-hour SOFT HOLD; each admin reply resets the timer.
- Admin `Salaar wait` = HARD MUTE and `Continue Salaar` = AUTO.
- AUTO / WAIT badges in the admin inbox.
- Confused/low-confidence fallback points customers to WhatsApp text at `03238878009` without a WhatsApp API integration.
- 2-second polling from Phase 1 remains in place.

## Out of scope
No Ready button, Rs 300 flow, ops email, `wa.me` order link, Reseller Club signup, Prime Skill crawl, WhatsApp Cloud API, or PrimeHub website deployment.

## Environment
Copy `.env.example` to `.env.local` and set:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
ADMIN_PASSWORD=choose-a-strong-password
NEXT_PUBLIC_APP_URL=http://localhost:3000
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-haiku-latest
```

Configure either OpenAI or Anthropic. If both keys are blank, the public chat remains usable and shows a friendly Salaar configuration message.

## Run locally

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

## Railway / VPS
Attach PostgreSQL, set the environment variables above, then run:

```bash
npm install
npm run build
npm start
```

## CI
`.github/workflows/phase2-ci.yml` runs on Phase 2 pushes and PRs and executes dependency install, `npm ci`, lint, TypeScript checking, unit tests, and the production Next.js build.

## Phase 2 verify
- [ ] Preview URL opens the customer widget and `/admin` inbox.
- [ ] Widget: ask for bangles → 2–3 catalog products appear with images and `Add to cart`.
- [ ] Add one product → cart summary updates.
- [ ] Ask for bangles again → previously shown SKUs are not repeated.
- [ ] Ask `kuch aur` → Salaar can rotate to a new set.
- [ ] `/admin`: send a human reply → badge becomes WAIT and Salaar stays silent.
- [ ] Click `Continue Salaar` → badge becomes AUTO and Salaar can answer again.
- [ ] Click `Salaar wait` → hard mute remains WAIT until manually continued.
- [ ] Remove/omit LLM keys → app still loads and chat shows a friendly configuration error.
- [ ] GitHub Phase 2 CI is green, including lint, typecheck, tests, and `npm run build`.

## Preview URL
Pending a standalone `primehub_bot` Railway/Vercel environment with PostgreSQL. Do not point this repo at the existing PrimeHub website Vercel project.
