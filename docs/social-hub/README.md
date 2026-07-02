# The Hub — Split Into Two Projects

Date: July 2026 · Supersedes the combined workup in `ANALYSIS-AND-PLAN.md`

The original idea — one central post that fans out to social media accounts
AND seller/buyer apps — has been split into **two independent projects**:

| | Project A | Project B |
|---|---|---|
| Doc | [`PROJECT-A-SOCIAL-CROSSPOSTER.md`](./PROJECT-A-SOCIAL-CROSSPOSTER.md) | [`PROJECT-B-MARKETPLACE-CROSSLISTER.md`](./PROJECT-B-MARKETPLACE-CROSSLISTER.md) |
| One line | One post → every social platform in its native format, no user input | One listing (photos, description, price…) → every seller app in its native listing format |
| Content | Free-form text + media | Structured listing data |
| Targets | Bluesky, X, Instagram, Facebook, Threads, TikTok, Pinterest, LinkedIn | eBay, Poshmark, Mercari, Etsy, Depop, FB Marketplace, Shopify |
| Integration reality | Official APIs exist everywhere | Only eBay/Etsy/Shopify have APIs; the rest need a browser extension |
| Hard problem | Content transformation quality (limits, hashtags, media specs) | Category/field mapping + no-API platforms |
| Delivery model | Fully automatic server-side publish | Automatic where APIs exist; extension-assisted elsewhere |

## Why split?

1. **Different data models.** A social post is text + media. A listing is a
   structured product record (price, condition, category, shipping,
   size/brand attributes). Forcing both through one composer made each worse.
2. **Different integration risk.** Project A is all official APIs — stable,
   automatable, ToS-clean. Project B's biggest platforms (Poshmark, Mercari,
   FB Marketplace) have no APIs and need extension-based form-filling.
   Splitting keeps Project A's reliability unpolluted by Project B's risk.
3. **Different "done" bars.** A can genuinely be zero-user-input. B, on the
   no-API platforms, is at best "review and click Publish" — human-in-the-loop
   by design.
4. **Ship faster.** A alone is a 3–5 week project. B alone is 4–8 weeks.
   Combined, everything waited on everything.

## What they share (build once, reuse)

Even as separate projects, they should share DNA — same language (TypeScript),
same adapter pattern, same infrastructure choices — so a future "bridge"
feature (list an item in B → auto-announce it via A) is easy:

- **Adapter contract**: `validate(content) → transform(content) → publish(payload)`
- **Connection manager**: OAuth flows, encrypted token storage, refresh
- **Media pipeline**: original upload → per-platform renditions (sharp/ffmpeg)
- **Publish queue**: per-target jobs, retries, partial-failure dashboard

Recommended layout: one monorepo, two apps, shared packages —
`packages/core`, `packages/media`, `apps/social-poster`, `apps/cross-lister`.
They deploy and evolve independently but never duplicate plumbing.

## Recommended order

**Build Project A first.** It's smaller, every integration is an official
API, and it proves the shared core (adapters, transformer, queue, OAuth)
that Project B then inherits. B's eBay/Etsy adapters slot straight into a
proven pipeline; its extension work becomes the only new frontier.

## Platform research (July 2026) — carried over

Full per-platform API details, pricing, competitor landscape, risks, and
sources are in the original combined workup: [`ANALYSIS-AND-PLAN.md`](./ANALYSIS-AND-PLAN.md).
Headlines that shaped the split:

- X is pay-per-use since Feb 2026 (~$0.015/text post, ~$0.20/post with URL)
- Meta (IG/FB/Threads) is free but needs App Review only for *production*
  apps — personal/dev-mode use of your own accounts avoids it
- TikTok posting requires an audit or posts are forced private; video-only
- Poshmark, Mercari, Depop, FB Marketplace: **no official listing APIs** —
  competitors (Vendoo, Crosslist, List Perfectly) use browser extensions
- eBay Sell APIs and Etsy Open API v3 are solid, well-documented
