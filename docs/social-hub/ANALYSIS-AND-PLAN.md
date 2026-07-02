# Central Posting Hub — Analysis & Project Plan

**One central post → automatically reformatted and published to every connected social media account and seller/buyer marketplace, in each platform's native format.**

Date: July 2026 · Status: Concept analysis / project workup

---

## 1. The Idea in One Picture

```
                    ┌──────────────────────────┐
                    │      CENTRAL POST         │
                    │  title · body · media     │
                    │  price · tags · category  │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   TRANSFORMATION LAYER    │
                    │ per-platform formatting:  │
                    │ char limits, image specs, │
                    │ hashtags, listing fields  │
                    └────────────┬─────────────┘
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
      ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
      │ SOCIAL       │  │ MARKETPLACES │  │ COMMERCE     │
      │ Instagram    │  │ eBay         │  │ Shopify      │
      │ Facebook     │  │ Etsy         │  │ FB Shops     │
      │ X / Threads  │  │ Mercari*     │  │              │
      │ TikTok       │  │ Poshmark*    │  │              │
      │ Bluesky      │  │ FB Mrktpl.*  │  │              │
      │ Pinterest    │  │ Depop*       │  │              │
      └──────────────┘  └──────────────┘  └──────────────┘
                        * no official API — see §3
```

Two distinct content types flow through the same pipeline:

1. **Announcements** (social posts): text + media, optimized per network.
2. **Listings** (marketplace items): structured data — price, condition, category,
   shipping — mapped to each marketplace's listing schema.

A killer feature of the combined hub: *list an item on marketplaces AND
auto-announce it on socials in one action* ("New in the shop: …" with a link).
Most competitors do one side or the other, not both.

---

## 2. Is This Worth Building? (Honest Assessment)

### The good news
- The concept is proven — people pay real money for half-solutions today.
  Buffer/Hootsuite/Postiz handle socials ($6–$100+/mo per user); Vendoo,
  Crosslist, List Perfectly handle marketplaces ($9–$70/mo). Nobody owns the
  intersection well.
- Reseller / small-seller market is large and underserved on the "social
  promotion of listings" side.
- If built for **personal use first**, almost all platform costs are $0 or
  trivial, and API approval hurdles are much lower.

### The hard news (know these before writing code)
1. **The product is 20% code, 80% platform-relationship management.** Every
   platform has its own OAuth flow, app review process, rate limits, media
   specs, and deprecation schedule. Adapters break when platforms change —
   this is a maintenance treadmill, priced into competitors' subscriptions.
2. **Several key marketplaces have NO official listing API** (Poshmark,
   Mercari, Depop, Facebook Marketplace for individuals). Competitors use
   browser extensions that form-fill the listing pages — a gray area under
   those platforms' ToS. It works (Vendoo et al. operate openly) but carries
   account-ban risk and constant breakage.
3. **X (Twitter) is no longer free**: pay-per-use since Feb 2026 (~$0.01–0.015
   per text post, ~$0.20 per post containing a URL — which listing
   announcements would). Fine for personal volume, a real cost at scale.
4. **App review gauntlets**: Meta requires App Review + Business Verification
   for production Instagram/Facebook publishing; TikTok requires an audit or
   all posts are forced private; LinkedIn requires partner approval.
   For a *personal-use* app these are mostly avoidable (dev-mode apps can post
   to your own accounts).

### Verdict
**Feasible and worthwhile as a personal tool, with a credible path to a
product later.** Build it for your own accounts first — that sidesteps most
app-review pain, validates the transformation engine, and produces something
genuinely useful in weeks, not months. Decide about productizing after it's
running.

---

## 3. Platform Integration Landscape (July 2026)

### Social networks

| Platform | API | Cost | Access hurdle | Notes |
|---|---|---|---|---|
| Facebook Pages | Graph API | Free | App Review for production; dev mode fine for own Pages | Personal *profiles* can't be posted to via API — Pages only |
| Instagram | Graph API (Content Publishing) | Free | App Review + Business Verification for production | Requires Business/Creator account; ~50 posts/24h; images ≥ JPEG specs, video via resumable upload |
| X (Twitter) | v2 API | Pay-per-use: ~$0.015/text post, ~$0.20/post with URL; tiers from $100/mo | Credit card | No free tier for new devs since Feb 2026 |
| Threads | Threads API | Free | Meta App Review | Similar to IG flow |
| TikTok | Content Posting API | Free | **Audit required** or posts forced private | Video-only; ~15 posts/day/creator |
| Bluesky | AT Protocol | Free | None — open protocol | Easiest integration; great first adapter |
| Pinterest | Pinterest API | Free | Standard access request | Rate-limited per category; good fit for product pins |
| LinkedIn | Community Mgmt API | Free | Partner approval (slow) | Deprioritize unless needed |
| YouTube (Shorts) | Data API | Free quota units | Standard | Only if video content matters |

### Marketplaces / seller apps

| Platform | Official listing API? | Realistic integration path |
|---|---|---|
| eBay | **Yes** — Sell APIs (Inventory/Listing) | First-class API integration. Best-documented marketplace API |
| Etsy | **Yes** — Open API v3 | API integration; app approval is straightforward |
| Shopify | **Yes** — Admin API | Full API if you run a Shopify store |
| Facebook Marketplace | **No** (individuals). Commerce via FB Shops/Commerce Manager only | Browser extension / manual-assist, or route through FB Shops |
| Poshmark | **No** | Browser extension form-fill (what Vendoo/Crosslist do). ToS gray area |
| Mercari | **No** public API | Same — extension form-fill |
| Depop | **No** public API | Same |
| Craigslist | **No** | Manual-assist only (prefill + copy) |

**Design consequence:** the hub needs **three adapter tiers**:

- **Tier 1 — API adapters** (server-side, reliable): eBay, Etsy, Shopify,
  Meta, X, Bluesky, Pinterest, TikTok.
- **Tier 2 — Extension adapters** (browser extension that form-fills the
  platform's listing page while you're logged in): Poshmark, Mercari, Depop,
  FB Marketplace. Higher maintenance, ToS risk — make these opt-in and phase 3+.
- **Tier 3 — Manual-assist** (hub renders the post perfectly formatted for the
  platform with a copy button + deep link): everything else, and the instant
  fallback whenever Tier 1/2 breaks. Cheap to build, zero risk, ships day one.

Tier 3 matters more than it sounds: it means *every* platform is "supported"
from the MVP onward, and automation is a per-platform upgrade rather than a
blocker.

---

## 4. Competitive Landscape

| Product | Covers | Price | Gap we'd fill |
|---|---|---|---|
| Buffer / Hootsuite / Later | Social only | $6–$100+/mo | No marketplace listings |
| Postiz (open source) | Social only | Self-host free | Good reference codebase; no marketplaces |
| Vendoo | Marketplaces (10+) | $8.99–$69.99/mo | No social announcement side |
| Crosslist | Marketplaces (11+) | $29.99–$44.99/mo | Same |
| List Perfectly | Marketplaces (12+) | $29–$69/mo | Same; US-only |
| Blotato / unified-post APIs | Social posting via one API | usage-priced | Could be *used by* our hub to shortcut social adapters |

The intersection — "one post that both lists the item and promotes it" — is
the differentiated slice.

---

## 5. Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  WEB APP (Next.js/React)                                     │
│  composer · per-platform preview · connection mgr · history  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST/tRPC
┌──────────────────────────▼──────────────────────────────────┐
│  API SERVER (Node.js + TypeScript)                           │
│  ┌────────────┐ ┌───────────────┐ ┌───────────────────────┐ │
│  │ Post Core  │ │ Transformer   │ │ Connection Manager    │ │
│  │ canonical  │ │ per-platform  │ │ OAuth flows, token    │ │
│  │ post model │ │ format rules  │ │ refresh, encrypted    │ │
│  │            │ │ + validation  │ │ credential store      │ │
│  └────────────┘ └───────────────┘ └───────────────────────┘ │
│  ┌──────────────────────────────────────────────────────── ┐│
│  │ Adapter Registry (uniform interface per platform)        ││
│  │  validate(post) → publish(post) → status/permalink       ││
│  └──────────────────────────────────────────────────────── ┘│
└───────┬──────────────────────┬──────────────────────────────┘
        │                      │
┌───────▼────────┐   ┌─────────▼──────────┐   ┌───────────────┐
│ Job Queue      │   │ PostgreSQL          │   │ Media Store   │
│ (BullMQ/Redis) │   │ posts, accounts,    │   │ (S3/local)    │
│ retries,       │   │ publish results,    │   │ originals +   │
│ scheduling     │   │ platform mappings   │   │ per-platform  │
└────────────────┘   └────────────────────┘   │ renditions    │
                                              └───────────────┘
```

### Core concepts

**Canonical Post Model** — the single source of truth:

```ts
interface CentralPost {
  kind: 'announcement' | 'listing';
  title: string;
  body: string;                    // long-form; adapters truncate/rewrite
  media: MediaAsset[];             // originals; renditions generated per platform
  tags: string[];
  link?: string;
  listing?: {                      // only for kind: 'listing'
    price: Money;
    condition: string;
    category: string;              // hub taxonomy → mapped per marketplace
    quantity: number;
    shipping?: ShippingProfile;
    attributes: Record<string, string>;  // brand, size, color…
  };
  targets: TargetSelection[];      // which accounts, with per-target overrides
  scheduleAt?: Date;
}
```

**Adapter interface** — every platform (API, extension, or manual) implements
the same contract, so the core never special-cases platforms:

```ts
interface PlatformAdapter {
  id: string;                                  // 'ebay', 'instagram', …
  tier: 'api' | 'extension' | 'manual';
  capabilities: Capabilities;                  // maxChars, mediaSpecs, listingFields…
  validate(post: CentralPost): ValidationResult;   // pre-flight, drives UI warnings
  transform(post: CentralPost): NativePayload;     // canonical → native format
  publish(payload: NativePayload, auth: Connection): Promise<PublishResult>;
}
```

**Transformer rules per platform** (data-driven where possible): character
limits (X 280 vs IG 2,200 caption), hashtag conventions, image aspect/size
renditions, video specs, marketplace category mapping, required listing
fields. The **per-platform live preview** in the composer is the feature that
makes the product feel magical — invest here.

**Publish pipeline**: composer → validate against all selected targets (show
warnings inline) → save post → enqueue one job per target → adapter publishes
with retry/backoff → results dashboard (link to live post, or actionable
error + "retry" / "do manually" fallback). Partial failure is normal and the
UX must treat it as such.

### Stack recommendation

- **TypeScript end-to-end** (this repo is already JS/TS — consistent skillset)
- **Next.js** front end, **Node/Fastify or Next API routes** back end
- **PostgreSQL** + **Prisma**, **Redis + BullMQ** for the queue
- **sharp**/**ffmpeg** for media renditions
- Credentials encrypted at rest (libsodium sealed boxes or KMS)
- Deploy: single VPS or Fly.io/Railway for personal use

Consider **forking/studying Postiz** (open-source, MIT, Node/NestJS) for the
social half — its adapters solve OAuth + publish for most networks already.
Even if not forked, it's the best reference implementation.

---

## 6. Phased Plan

### Phase 0 — Foundations (1–2 weeks)
- New repo (this one is the DEX bot — the hub should live separately)
- Canonical post model, adapter interface, Postgres schema, queue skeleton
- Composer UI v0: create post, pick targets, see stored history
- **Manual-assist (Tier 3) for ALL platforms**: perfectly formatted
  per-platform output with copy buttons and deep links
- ✅ *Milestone: hub already useful — one write-up, formatted for everywhere.*

### Phase 1 — First real integrations (2–3 weeks)
- **Bluesky adapter** (no approval needed — proves the pipeline end-to-end)
- **eBay Sell API adapter** (best marketplace API; listing model forces the
  listing schema to get real)
- OAuth connection manager + encrypted token store + refresh
- Per-platform preview rendering in composer
- ✅ *Milestone: one click posts to Bluesky and lists on eBay.*

### Phase 2 — Core socials (3–4 weeks)
- **Meta adapter**: Facebook Page + Instagram (dev-mode app for own accounts;
  Business/Creator IG account required)
- **Etsy adapter**
- **X adapter** (pay-per-use key; add a per-post cost display in the UI)
- Media pipeline: renditions per platform spec (sharp/ffmpeg)
- Scheduling + retry dashboard
- ✅ *Milestone: daily-driver for socials + two marketplaces.*

### Phase 3 — The extension frontier (3–4 weeks, optional/risk-accepted)
- Browser extension (WebExtension, Chrome+Firefox) that reads a pending
  listing from the hub and form-fills Poshmark / Mercari / Facebook
  Marketplace listing pages for you to review and submit
- Human-in-the-loop by design (you click "Publish" on the platform page) —
  keeps it closer to assisted posting than bot automation, reduces ban risk
- ✅ *Milestone: parity with Vendoo/Crosslist coverage on the big no-API apps.*

### Phase 4 — Round-out & polish (ongoing)
- TikTok (video pipeline + audit if going public), Pinterest, Threads
- Cross-posting recipes: "when listed on eBay → announce on IG/X/Bluesky
  with permalink"
- Inventory sync / de-list-everywhere-when-sold (the feature resellers pay
  Vendoo for)
- Analytics: publish success rates, engagement pull-back where APIs allow

**Total to a genuinely useful personal tool: roughly 6–9 weeks of part-time
work (Phases 0–2).** Phase 3 is where maintenance burden begins — decide then
whether manual-assist is good enough for the no-API platforms.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Platform API changes break adapters | **Certain, recurring** | Adapter isolation; contract tests per adapter; Tier-3 fallback always available |
| Extension automation → account warnings/bans (Poshmark, Mercari, FB) | Medium | Human-in-the-loop submits; rate discipline; make Tier 2 opt-in with clear warning; personal accounts only at first |
| Meta/TikTok app review pain | High *if productized* | Stay in dev mode for personal use; defer review until product decision |
| X API costs creep | Low at personal volume | Show per-post cost; make X optional |
| Scope creep (every platform wants special handling) | High | Capabilities-driven core; new platform = new adapter file, never core changes |
| Token/credential leakage | Low but severe | Encrypt at rest, never log tokens, scoped OAuth, rotate on suspicion |

---

## 8. Decisions to Make Before Phase 0

1. **Personal tool vs. product from day one?** (Recommend: personal first —
   changes app-review posture, hosting, and multi-tenancy decisions.)
2. **Which platforms do YOU actually use?** The list above is the universe;
   your real accounts define Phase 1–2 order. (E.g., if Poshmark is your #1,
   the extension work moves up.)
3. **Build the social half or buy it?** Postiz self-hosted (or a unified-post
   API like Blotato) could eliminate most social adapters, leaving us to build
   only the listing/marketplace side + the unifying composer.
4. **New repository name** — this analysis lives in the dex-bot repo for
   review, but the project itself should start clean.

---

## 9. Sources

- [X (Twitter) API pricing 2026 — Blotato](https://www.blotato.com/blog/twitter-api-pricing)
- [Social Media APIs in 2026: Developer's Guide — Blotato](https://www.blotato.com/blog/social-media-api)
- [Social media API rules, rate limits & media specs 2026 — Postproxy](https://postproxy.dev/blog/social-media-platform-api-rules-rate-limits-media-specs/)
- [X API pricing tiers 2026 — Netrows](https://www.netrows.com/blog/x-twitter-api-pricing-tiers-2026)
- [Multi-platform posting APIs — Buffer](https://buffer.com/resources/social-media-api-multi-platform-posting/)
- [Vendoo](https://vendoo.co/) · [Crosslist](https://crosslist.com/)
- [Best cross-listing software for resellers 2026 — ResaleOS](https://www.resaleos.co/blog/comparing-the-20-best-cross-listing-software-for-resellers-in-2026-the-complete-buyer-s-guide)
- [Mercari crosslisting tools 2026 — Nifty](https://nifty.ai/post/mercari-cross-listing)
- [Cross-listing app pricing comparison — Voolist](https://www.voolist.com/blog/best-cross-listing-apps-2026)
