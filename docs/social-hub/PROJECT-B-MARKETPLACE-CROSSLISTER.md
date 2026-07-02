# Project B — Marketplace Cross-Lister

**Create one selling listing — photos, description, price, condition,
category — and it becomes a native listing on every connected seller app:
eBay, Poshmark, Mercari, Etsy, Depop, Facebook Marketplace.**

Date: July 2026 · See [`README.md`](./README.md) for how this relates to Project A.

---

## 1. Product Definition

### The promise
The user photographs an item once, fills in one listing form, and the system
creates that listing on every selected marketplace in its native format —
correct category, correct fields, correct photo specs — with as little
further input as each platform physically allows.

### The core honesty: two delivery modes
Unlike social platforms, marketplaces split hard on what's possible:

- **API marketplaces (eBay, Etsy, Shopify):** true zero-input publishing,
  server-side, fully automatic. Same UX as Project A.
- **No-API marketplaces (Poshmark, Mercari, Depop, FB Marketplace):** there
  is no official way to create a listing programmatically. The industry
  answer (Vendoo, Crosslist, List Perfectly — $9–$70/mo products) is a
  **browser extension that form-fills the listing page** while you're logged
  in; you review and click the platform's own Publish button.

So Project B's honest promise is: *automatic where the platform allows it,
one-click-assisted everywhere else.* The human clicking "Publish" on
Poshmark's own page is both a ToS-risk reducer and a quality gate.

### What makes this harder than social posting
1. **Structured data, not prose.** Price, condition enums, quantity,
   shipping profiles, brand/size/color attributes — each marketplace has its
   own required fields and vocabulary.
2. **Category mapping.** eBay has ~20k categories with per-category item
   specifics; Poshmark has its own tree; Etsy has taxonomy + attributes.
   The hub needs one internal taxonomy plus per-marketplace mapping (start
   with the handful of categories *you* actually sell in — don't boil the
   ocean).
3. **Lifecycle, not fire-and-forget.** Listings live on: item sells on
   marketplace X → must be de-listed from Y and Z fast (double-sell risk).
   Inventory state sync is the feature resellers actually pay for.

### Out of scope (v1)
- Social announcements (Project A; a bridge comes later)
- Order management / shipping labels
- Repricing tools, offers/negotiation automation
- Bulk import of existing listings (v2 — big quality-of-life, not core)

---

## 2. Marketplace Targets & Integration Facts (July 2026)

| # | Marketplace | Listing API? | Path | Notes |
|---|---|---|---|---|
| 1 | **eBay** | ✅ Sell APIs (Inventory + Offer) | API | Best-documented marketplace API; sandbox available; category + item-specifics lookup APIs |
| 2 | **Etsy** | ✅ Open API v3 | API | Straightforward app approval; handmade/vintage/supplies policy applies |
| 3 | **Shopify** | ✅ Admin API | API | Only if you run a store |
| 4 | **Poshmark** | ❌ | Extension | Form-fill; the biggest Vendoo use case |
| 5 | **Mercari** | ❌ | Extension | Form-fill |
| 6 | **Facebook Marketplace** | ❌ for individuals | Extension | Commerce Manager/Shops API exists only for approved businesses |
| 7 | **Depop** | ❌ | Extension | Form-fill |
| 8 | Craigslist | ❌ | Manual-assist | Prefill + copy only |

Every no-API platform also gets **manual-assist** as a permanent fallback:
the hub renders the listing formatted for that marketplace (title at its max
length, description, price, photo set) with copy buttons — useful from day
one and whenever the extension breaks.

---

## 3. Architecture

Shares `packages/core` and `packages/media` with Project A (adapter
contract, OAuth/connection manager, queue, media renditions). New pieces:

```
┌─────────────────────────────────────────────────────────┐
│ WEB APP — listing composer (photo upload, structured     │
│ fields, per-marketplace preview), inventory dashboard    │
└──────────────────────────┬──────────────────────────────┘
┌──────────────────────────▼──────────────────────────────┐
│ API SERVER                                                │
│  CanonicalListing ─► Field/Category Mapper per market     │
│  Adapter Registry:                                        │
│    api-adapters:  ebay · etsy · shopify   (server pub)    │
│    ext-adapters:  poshmark · mercari · fbm · depop        │
│                   (payload handed to browser extension)   │
│  Inventory State Machine: draft → listed(n) → sold →      │
│                   delist-others → archived                │
└───────┬──────────────────┬──────────────────┬────────────┘
   Job Queue          PostgreSQL          Media Store
                 listings · per-market   originals + per-
                 status · sold events    market photo specs
                          ▲
┌─────────────────────────┴───────────────────────────────┐
│ BROWSER EXTENSION (Chrome/Firefox WebExtension)          │
│  pulls pending listing payloads from hub API →           │
│  opens marketplace "create listing" page →               │
│  form-fills fields + uploads photos →                    │
│  user reviews, clicks the platform's Publish →           │
│  extension captures listing URL → reports back to hub    │
└──────────────────────────────────────────────────────────┘
```

```ts
interface CanonicalListing {
  title: string;                  // adapters truncate: eBay 80 chars, Posh 50…
  description: string;
  photos: MediaAsset[];           // per-market count/size/aspect renditions
  price: Money;
  condition: ConditionEnum;       // mapped per marketplace vocabulary
  category: HubCategoryId;        // internal taxonomy → per-market mapping
  attributes: Record<string,string>;  // brand, size, color, material…
  quantity: number;
  shipping?: ShippingProfile;
  targets: MarketplaceAccount[];
}

interface MarketplaceAdapter {
  id: MarketplaceId;
  mode: 'api' | 'extension' | 'manual';
  requiredFields(category: HubCategoryId): FieldSpec[];   // drives dynamic form
  validate(l: CanonicalListing): Warning[];
  transform(l: CanonicalListing): NativeListing;
  publish?(n: NativeListing, conn: Connection): Promise<PublishResult>; // api mode
}
```

Design notes:
- `requiredFields()` makes the composer **dynamic**: pick eBay + Poshmark and
  the form shows the union of what both need, asked once.
- The **inventory state machine** is core, not a feature: `sold` on any
  market triggers delist jobs on the others (API markets: automatic;
  extension markets: a prominent "delist now" task with one-click assist).
- Extension is human-in-the-loop *by design* — no headless automation, no
  scheduled bot actions on no-API platforms. This is materially lower
  ban-risk than full automation, but still technically against some
  platforms' ToS; personal account, opt-in, eyes open.

---

## 4. Plan

### Phase B0 — Listing core + manual-assist everywhere (week 1–2)
- `CanonicalListing` model, internal category taxonomy (start with only the
  categories you sell), dynamic composer with photo upload
- **Manual-assist output for all 8 marketplaces** (formatted per-market
  listing + copy buttons + deep link to each "create listing" page)
- ✅ *Milestone: one form replaces retyping a listing 5 times — already
  saves real time with zero platform risk.*

### Phase B1 — eBay, for real (week 2–4)
- **eBay Sell API adapter**: OAuth, category suggestion + item specifics
  lookup, photo upload, publish, revise, end-listing
- Publish-results dashboard; sandbox tests
- ✅ *Milestone: one click creates a live eBay listing.*

### Phase B2 — Etsy + inventory sync (week 4–5)
- **Etsy v3 adapter** (if you sell there; else promote B3)
- Inventory state machine + sold-event polling on API markets →
  auto-delist elsewhere
- ✅ *Milestone: sell it once, everywhere else updates.*

### Phase B3 — The extension (week 5–8, risk-accepted)
- WebExtension scaffold + hub pairing (secure token)
- **Poshmark** form-fill first (your call), then **Mercari**, then
  **FB Marketplace**, then Depop — one at a time, each is its own
  reverse-engineering effort and its own maintenance commitment
- Extension reports listing URLs back; sold-detection on extension markets
  (page-check assist) feeds the same state machine
- ✅ *Milestone: Vendoo-class coverage, self-hosted, $0/mo.*

### Phase B4 — Later
- Bulk import of existing listings; relist stale items
- The **Project A bridge**: on publish, auto-announce on socials with photo +
  price + link (this is the reunited original vision)

**Total: ~2 weeks to genuinely useful (B0), ~4–5 weeks to automated
eBay/Etsy, ~8 weeks to full extension coverage.**

---

## 5. Risks

| Risk | Level | Mitigation |
|---|---|---|
| Extension form-fill breaks when marketplaces redesign pages | **Certain, recurring** | One adapter per market; selector configs updatable without re-release; manual-assist always available |
| Account warnings/bans on no-API platforms | Medium | Human-in-the-loop publish only; no headless/scheduled automation; rate discipline; opt-in with explicit warning |
| Category/field mapping ballooning | High | Ship only the categories you sell; add on demand |
| Double-sell (item sells on two markets) | Medium | Inventory state machine + fast delist jobs is a v1 core feature, not an add-on |
| eBay/Etsy API quotas & policy compliance | Low | Personal volumes are far under limits |

---

## 6. Open Decisions

1. **Which marketplaces do you actually sell on, ranked?** This reorders
   B1–B3 entirely (e.g., Poshmark-first would pull the extension forward).
2. **What do you sell?** Determines the starting taxonomy and which item
   attributes (size/brand vs. specs vs. condition grades) the composer needs.
3. Accept the extension approach for the no-API apps (Vendoo-style,
   human-in-the-loop), or stay manual-assist-only there?
4. eBay first or Poshmark first for the "real automation" milestone?
