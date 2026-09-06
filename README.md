# PrimeHub Bot — Phase 5

Standalone repo: `primehubpk/primehub_bot`. This is the Salaar bot application and admin inbox. The ecommerce website remains in `primehubpk/primehub`; the bot is not copied into that repo.

## What is included
Phases 1–4 remain intact: customer widget, Salaar LLM, mock catalog/cart, anti-repeat products, admin inbox, AUTO/WAIT controls, Ready/Rs 300 flow, ops email, `wa.me/923238878009`, order Complete, Prime Skill/Reseller knowledge, reseller approval queue, and NEED YOU escalation.

Phase 5 adds:
- `/embed` as the website-safe widget page.
- Parent-window resize messages so the website iframe is small when the bubble is closed and expands when chat opens.
- `ALLOWED_WEBSITE_ORIGINS` CORS handling for bot APIs and `frame-ancestors` protection for `/embed`.
- Website embedding is done with only a small iframe loader in `primehubpk/primehub`, controlled by that website's `BOT_PUBLIC_URL` env.
- If the website does not have `BOT_PUBLIC_URL`, the store loads normally and no chat iframe is rendered.

## Environment

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
DATABASE_SSL=true
ADMIN_PASSWORD=choose-a-strong-password
NEXT_PUBLIC_APP_URL=https://bot.example.com
ALLOWED_WEBSITE_ORIGINS=https://primehubmall.com,https://www.primehubmall.com

# Configure either LLM provider
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-haiku-latest

# Orders + reseller approval email
OPS_EMAIL=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=

# PrimeHub website feature links
PRIME_SKILL_URL=https://www.primehubmall.com/prime-skill
RESELLER_CLUB_URL=https://www.primehubmall.com/reseller-club
```

`ALLOWED_WEBSITE_ORIGINS` is a comma-separated list of exact origins. Include local website development origin when testing locally, for example `http://localhost:3001`.

## Local run

```bash
npm install
npm run lint
npm run typecheck
npm test
npm run build
npm run dev
```

Bot public page: `http://localhost:3000`  
Embeddable widget: `http://localhost:3000/embed`  
Admin inbox: `http://localhost:3000/admin`  
Knowledge/reseller admin: `http://localhost:3000/admin/phase4`

For a local two-app test, run the bot on port 3000 and the website on a different port, e.g. 3001. Set the website env:

```env
BOT_PUBLIC_URL=http://localhost:3000
```

and include `http://localhost:3001` in the bot's `ALLOWED_WEBSITE_ORIGINS`.

## Website embed

The ecommerce repo contains only a small `SalaarEmbed` component in the global layout. It loads `${BOT_PUBLIC_URL}/embed` in an iframe. It does not copy Salaar, the database, admin inbox, cart logic, or LLM code into the website.

Logged-in customer identity is not passed unless the website can expose a stable user identifier safely. The current embed therefore keeps the bot's existing guest/session cookie behavior rather than exposing private auth data from the store.

## Production: one VPS

Production target is **one VPS, one bot codebase, one server bill**.

Deploy this `primehub_bot` application (or its future monorepo Salaar app) to the VPS. Do **not** deploy the entire `primehubpk/primehub` ecommerce source as the bot service. The website only points `BOT_PUBLIC_URL` at the public bot URL.

A practical single-VPS layout later can be:

```text
primehub_bot/
  app/                    # Salaar web/admin/API
  lib/                    # shared bot services
  modules/
    mp-uploader/          # future M&P uploader
    tiktok-uploader/      # future TikTok uploader
```

The later uploader modules should share the same repository/runtime infrastructure and can use the same process manager or a small set of processes on that VPS. They do not require separate Railway/Vercel projects just because they are separate modules.

Recommended VPS runtime:
- Node.js 22+
- PostgreSQL reachable through `DATABASE_URL`
- reverse proxy such as Nginx/Caddy with HTTPS
- process manager such as systemd or PM2
- environment variables kept outside Git
- `npm ci && npm run build && npm start`

## Phase 5 verify

- [ ] `npm ci`, lint, typecheck, unit tests, and production build pass in GitHub Actions.
- [ ] `/embed` renders the Need help bubble.
- [ ] Website with `BOT_PUBLIC_URL` set shows the widget globally on home/product/cart pages through the root layout.
- [ ] Sending a message through the embedded widget creates/updates the same bot conversation visible in `/admin`.
- [ ] Phase 3 cart + Ready/Rs 300 flow still works inside the embedded widget.
- [ ] Website with `BOT_PUBLIC_URL` missing still loads and simply hides chat.
- [ ] No WhatsApp Cloud API or auto-send WhatsApp implementation exists in this phase.

## Hosting rule

Do not require Railway and do not create a new paid host just for Phase 5. An already-existing preview may be used. The final production home is the single VPS described above.

Phase 6 WhatsApp Cloud API/coexistence is intentionally not implemented here.
