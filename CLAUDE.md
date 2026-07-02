# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A TypeScript trading bot that runs grid-trading or market-making strategies against the MetalX DEX on the XPR Network (Proton) blockchain. Running `npm run bot` places **real orders with real funds** on mainnet using the account in `PROTON_USERNAME`/`PROTON_PRIVATE_KEY` env vars — never run it casually while developing; use the testnet variant or tests instead.

## Commands

```bash
npm install

# Run the bot on mainnet (typechecks with `tsc --noEmit` first, then runs via ts-node ESM loader)
npm run bot

# Run against testnet (sets NODE_ENV=test, which layers config/test.json over default.json)
npm run bot:test

# Tests (mocha + chai + ts-node)
npm test

# Lint (airbnb-base; note: the script only lints .js files, not .ts)
npm run lint
npm run lint:fix
```

- `.mocharc.json` pins `spec` to `test/strategies/marketmaker.test.ts` only — `test/dexapi.test.ts` exists but is not run by `npm test`. To run a different or single test: `npx mocha test/dexapi.test.ts` or `npm test -- --grep "createBuyOrder"`.
- CI (`.github/workflows/test.js.yml`) runs `NODE_ENV=test npm run test` on Node 18/19. `src/dexrpc.ts` skips creating a signature provider when `npm_lifecycle_event === 'test'`, so tests work without a private key.
- There is no build output; the app runs directly from `src/` with ts-node (ESM, `"type": "module"`).

## Configuration

Uses the `config` npm package (`config/` directory):
- `config/default.json` — all bot settings: active `strategy` (`"gridBot"` or `"marketMaker"`), per-strategy `pairs` arrays, trade interval, RPC/API endpoints, optional Slack reporting (`slackBotToken`/`channelId`).
- `config/test.json` — testnet endpoint overrides, applied when `NODE_ENV=test`.
- `config/custom-environment-variables.json` — maps `PROTON_USERNAME` → `bot.username` and `PROTON_PRIVATE_KEY` → `bot.rpc.privateKey`. Both env vars are required to run the bot.

Config values may arrive as strings or numbers; use `configValueToFloat`/`configValueToInt` from `src/utils.ts` when parsing pair options (see `GridBotPairRaw` vs `GridBotPair` in `src/interfaces/config.interface.ts`).

## Architecture

Two distinct I/O layers, kept separate on purpose:

- **`src/dexapi.ts` — read-only, off-chain.** REST calls (with retry) to the DEX HTTP API (markets, order books, trades, open orders) and the Proton light API (balances). Also holds an in-memory markets cache (`byId`/`bySymbol` maps) populated by `dexapi.initialize()` at startup — `getMarketBySymbol()` returns `undefined` until that runs.
- **`src/dexrpc.ts` — on-chain writes.** Builds and signs transactions against the `dex` contract via `@proton/js`. `prepareLimitOrder()` does **not** submit; it pushes `transfer` + `placeorder` actions into a module-level `actions` array. `submitOrders()` appends `process` + `withdrawall` actions, transacts the whole batch, and clears the array. Order placement is therefore a two-phase prepare/submit flow.

**Strategy layer** (`src/strategies/`):
- `index.ts` holds a name→class registry (`strategiesMap`). `src/index.ts` looks up `config.strategy`, calls `initialize(config[config.strategy])`, then invokes `trade()` in an infinite loop every `tradeIntervalMS` (plus a parallel Slack-reporting loop via `src/slackapi.ts`).
- `base.ts` (`TradingStrategyBase`) provides shared helpers: `getMarketDetails()` (price + best bid/ask), `getOpenOrders()`, and `placeOrders()`, which submits prepared orders in batches of 10 with a delay between batches.
- `gridbot.ts` is stateful across trade ticks: it keeps `oldOrders` per pair, and on each tick diffs them against current open orders to detect fills, then places counter orders one grid level away (behavior controlled by the `gridPlacement` config flag). It also checks token balances via the light API before initial placement and skips the pair if funds are insufficient.
- `marketmaker.ts` is stateless: each tick it tops up buy/sell ladders around a base price (`AVERAGE`/`BID`/`ASK`/`LAST`) until `gridLevels` orders exist per side.

To add a strategy: implement `TradingStrategy` (extend `TradingStrategyBase`), register it in `strategiesMap` in `src/strategies/index.ts`, add its config section in `config/default.json`, and add the matching type to `BotConfig` in `src/interfaces/config.interface.ts`.

**Money math:** all price/quantity arithmetic uses `bignumber.js`, and amounts must be quantized to the market's `bid_token`/`ask_token` `precision`/`multiplier` from the market metadata. Follow the existing `getQuantityAndAdjustedTotal` pattern (quantity in bid token for sells, adjusted total in ask token for buys) rather than doing raw float math.

**Utility scripts:** `cancel-orders-mainnet.js` / `cancel-orders-testnet.js` are standalone plain-JS scripts (run with `node`) that cancel all open orders, or one market's orders by editing the `marketSymbol` const at the top of the file. They duplicate API logic rather than importing from `src/`.
