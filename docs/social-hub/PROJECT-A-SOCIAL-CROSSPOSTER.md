# Project A — Social Cross-Poster

**Write one post. It publishes to every connected social platform in that
platform's native format — automatically, with zero per-platform editing.**

Date: July 2026 · See [`README.md`](./README.md) for how this relates to Project B.

---

## 1. Product Definition

### The promise
The user writes a post *once* — text, images, maybe video, maybe a link —
hits Publish (or Schedule), and the system:

1. **Transforms** it into each target platform's native shape: trims/splits
   for character limits, moves hashtags where each platform wants them,
   resizes/crops media to platform specs, converts links to each platform's
   convention.
2. **Publishes** it to every connected account via official APIs, server-side,
   with no further user input.
3. **Reports** results: live permalink per platform, or a clear error with
   one-click retry.

### What "native format, no user input" actually requires
This is the whole product. The transformation engine must handle, per platform:

| Dimension | Examples of divergence |
|---|---|
| Length | X ~280 chars · Bluesky 300 · IG caption 2,200 · Facebook ~63k |
| Overflow strategy | X/Bluesky: auto-thread or smart-truncate with "…" · others: keep full text |
| Hashtags | IG: block at caption end (up to ~30) · X: 1–2 inline max · LinkedIn: 3–5 at end · Bluesky: inline, sparse |
| Links | X: costs more per post w/ URL, counts 23 chars · IG: **links in captions aren't clickable** → "link in bio" pattern or omit · FB: link preview card |
| Media | IG: JPEG, aspect 0.8–1.91, video via resumable upload · TikTok: video only · Pinterest: tall pins favored · X: 4 images max |
| Mentions | @handles differ per platform — can't be translated automatically; strip or map via a user-maintained alias table |
| Tone conventions | (v2) optional per-platform rewrite via LLM: casual for X, polished for LinkedIn |

**Design rule:** transformation is *deterministic and previewable*. The
composer shows a live rendering of exactly what each platform will receive.
"No user input" means no *required* input — per-target overrides remain
possible but never necessary.

### Explicitly out of scope (v1)
- Marketplace/selling listings of any kind (that's Project B)
- Engagement features (replies, DMs, analytics beyond publish success)
- Multi-user / team features
- AI rewriting (deterministic rules first; LLM polish is a clean v2 add-on)

---

## 2. Platform Targets & Integration Facts (July 2026)

Ordered by implementation priority:

| # | Platform | API | Cost | Access notes |
|---|---|---|---|---|
| 1 | **Bluesky** | AT Protocol | Free | No approval, open protocol. First adapter — proves the pipeline |
| 2 | **Facebook Pages** | Graph API | Free | Dev-mode app can post to your own Page without App Review. Personal profiles not postable via API |
| 3 | **Instagram** | Graph API Content Publishing | Free | Needs Business/Creator account linked to a FB Page. ~50 posts/24h. Dev mode OK for own account |
| 4 | **Threads** | Threads API | Free | Rides the same Meta app |
| 5 | **X (Twitter)** | v2 API | Pay-per-use: ~$0.015/text post, ~$0.20/post with URL | No free tier since Feb 2026. Show est. cost in composer |
| 6 | **Pinterest** | Pinterest API | Free | Standard access request; rate-limited |
| 7 | **TikTok** | Content Posting API | Free | Video-only. Unaudited apps → posts forced private; fine for testing, audit needed for real use. ~15 posts/day/creator |
| 8 | **LinkedIn** | Community Mgmt API | Free | Partner approval is slow — keep last / optional |

All Tier-1 official APIs — no ToS gray areas anywhere in Project A.

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────┐
│ WEB APP — composer with live per-platform previews,     │
│ account connections, schedule, publish-results history  │
└──────────────────────────┬─────────────────────────────┘
┌──────────────────────────▼─────────────────────────────┐
│ API SERVER (TypeScript)                                  │
│  CanonicalPost ──► Transformer (per-platform rules)      │
│                └─► Validator  (pre-flight warnings)      │
│  Connection Manager (OAuth, encrypted tokens, refresh)   │
│  Adapter Registry — one module per platform              │
└───────┬──────────────────┬─────────────────┬────────────┘
   Job Queue          PostgreSQL         Media Store
  (BullMQ/Redis)   posts · accounts    originals + per-
  retry/backoff    · publish results   platform renditions
```

```ts
interface CanonicalPost {
  body: string;                 // full-length source of truth
  media: MediaAsset[];
  tags: string[];
  link?: string;
  targets: TargetAccount[];     // selected connections
  overrides?: Record<PlatformId, Partial<CanonicalPost>>;  // optional, never required
  scheduleAt?: Date;
}

interface SocialAdapter {
  id: PlatformId;
  capabilities: {               // drives transformer + composer warnings
    maxChars: number; maxImages: number; video: VideoSpec | null;
    threading: boolean; linksClickable: boolean; hashtagStyle: 'inline'|'trailing';
  };
  validate(post: CanonicalPost): Warning[];
  transform(post: CanonicalPost): NativePayload;   // pure, deterministic, unit-testable
  publish(payload: NativePayload, conn: Connection): Promise<PublishResult>;
}
```

Key properties:
- `transform()` is **pure** → the live preview and the actual publish share
  one code path, and every platform's formatting rules get snapshot tests.
- Partial failure is a first-class UX: results screen per target with
  permalink / error / retry, never all-or-nothing.
- Stack: TypeScript, Next.js, PostgreSQL + Prisma, Redis + BullMQ,
  sharp + ffmpeg for renditions. Single VPS / Fly.io for personal use.

**Build-vs-borrow:** [Postiz](https://postiz.com) (open-source, MIT,
Node/NestJS) already implements OAuth + publishing for most of these
platforms. Options: (a) self-host it and accept its composer, (b) fork it,
or (c) build clean using its adapters as reference. Recommend **(c) with
heavy reference** — our differentiator is the transformation/preview engine,
which Postiz is weakest at; owning the core keeps Project B's shared-package
plan intact.

---

## 4. Plan

### Phase A0 — Core + first proof (week 1–2)
- Monorepo scaffold (`packages/core`, `packages/media`, `apps/social-poster`)
- Canonical post model, adapter contract, Postgres schema, queue
- Composer v0 with live preview framework
- **Bluesky adapter** end-to-end (no approval needed)
- ✅ *Milestone: type once, preview + publish to Bluesky.*

### Phase A1 — Meta family (week 2–4)
- Meta dev-mode app: **Facebook Page + Instagram + Threads** adapters
- Media rendition pipeline (aspect/size/format per platform)
- Transformation rules v1: length, hashtag placement, link handling
  (incl. IG "link in bio" behavior), overflow strategies
- Scheduling
- ✅ *Milestone: one post → Bluesky + FB + IG + Threads, zero edits.*

### Phase A2 — X, Pinterest, polish (week 4–5)
- **X adapter** with per-post cost estimate shown pre-publish
- **Pinterest adapter**
- Auto-threading for over-length posts (X/Bluesky)
- Results dashboard with retries; mention alias table
- ✅ *Milestone: daily driver across 6 platforms.*

### Phase A3 — Stretch (later)
- TikTok (video pipeline + audit), LinkedIn (partner approval)
- Optional LLM per-platform tone pass (behind preview + confirm)
- Best-time-to-post scheduling; the Project B bridge (auto-announce listings)

**Total to daily-driver: ~4–5 weeks part-time.**

---

## 5. Risks

| Risk | Level | Mitigation |
|---|---|---|
| Platform API changes | Certain, recurring | Isolated adapters + contract tests; core never touched |
| Meta App Review (if ever productized) | High then | Dev mode is fine for personal accounts; defer |
| X per-post costs | Low (personal volume) | Cost display; X optional |
| Transformation edge cases (emoji counting, grapheme lengths, URL char rules) | Medium | Snapshot-test each adapter against platform docs; preview = publish path |
| Token leakage | Low/severe | Encrypted at rest, scoped OAuth, never logged |

---

## 6. Open Decisions

1. Confirm the platform list against **your actual accounts** — priority
   order above assumes IG/FB matter most and LinkedIn least.
2. X: is ~$0.20/post-with-link acceptable, or skip X in v1?
3. Video from day one, or images-only v1? (Video adds TikTok/Reels but
   roughly doubles the media-pipeline work.)
4. Greenlight the monorepo/new-repo scaffold (this doc lives in dex-bot;
   the code should not).
