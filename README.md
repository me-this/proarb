# Triangular Arbitrage Searcher Bot (simulation-only)

Watches a 3-hop swap loop on a V3-style DEX (default: PancakeSwap V3 on
BNB Smart Chain) — e.g. `WBNB → Moolah → USDT → WBNB` — and logs every
profitable opportunity it finds. It **simulates** execution via `eth_call`;
it never signs or broadcasts a real transaction.

## How it decides

For each pass:

1. Get a live quote for each hop from the V3 **QuoterV2** contract
   (`quoteExactInputSingle`, called read-only). Because the quoter walks
   the pool's real liquidity, DEX fee and price impact for that hop are
   already baked into its output — we don't reimplement V3 tick math.
2. `gross_profit = final_WBNB − initial_WBNB`.
3. Subtract a **slippage buffer** (basis-point haircut on the output) and
   the **gas cost** (current gas price × a buffer multiplier × an
   estimated gas limit, converted to WBNB since gas is paid in native BNB
   which is 1:1 with WBNB).
4. `net_profit = gross_profit − slippage_buffer − gas_cost`.
5. **Any** opportunity with `gross_profit > 0` is appended to the CSV —
   there is no minimum-profit filter on logging, however small the edge.
6. Only when `net_profit > MIN_PROFIT_WBNB` does the bot go on to run a
   full-path **execution simulation** (see below) and record its result
   on the same row.

## Execution "simulation", precisely

`simulator.py` builds the real `exactInputSingle` calldata for a hop and
sends it as `eth_call` — a read-only call that tells you what a real
transaction *would* do, without spending gas, signing anything, or
touching funds. Since the wallet address configured here normally holds
no tokens, the simulator optionally applies an **`eth_call` state
override** that pretends the wallet already holds and has approved the
input token, so you can see whether the router/pool call itself would
succeed or revert (deadline logic, slippage checks, etc.) without funding
anything.

State overrides aren't supported by every RPC provider — most public
endpoints don't support them, while local forks (Anvil, Hardhat) and some
paid providers (Tenderly, QuickNode with debug/trace add-ons) do. If the
configured endpoint doesn't support it, the bot reports
`override_unsupported` and falls back to the quoter-based numbers instead
of failing.

**This project intentionally stops at simulation.** Turning this into a
bot that actually moves funds requires you to add transaction signing,
nonce/gas management, MEV-aware submission (e.g. a private relay to avoid
being frontrun), and much more careful testing — none of that is
included here.

## Mixed V2/V3 routing

Not every hop necessarily has its best liquidity on the same DEX version.
Each entry in `config.PATH` has a `dex_version` field (`"v3"` or `"v2"`):
V3 hops are priced via the QuoterV2 contract as described above; V2 hops
are priced via the PancakeSwap V2 Router's `getAmountsOut` (a
constant-product AMM quote, with the fixed 0.25% V2 fee already reflected
in the result). `arbitrage.py` dispatches each hop to the right one
automatically. The included default path is `WBNB/Moolah` (V3) →
`Moolah/USDT` (**V2** — the only pool with real liquidity for this pair)
→ `USDT/WBNB` (V3).

The full-path `eth_call` execution simulation in `simulator.py` currently
only builds calldata for a **V3** first hop; if your path's first hop is
V2, that simulation step is skipped and the bot falls back to the
quoter-based numbers (gross/net profit are unaffected either way, since
those always come from the quoter chain, not the simulator).

## Setup

```powershell
# from a Windows terminal (PowerShell), inside the cloned repo folder
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env   # fill in MOOLAH_ADDRESS, the three pool addresses, and RPC_URL
python main.py
```

You need Python 3.10+ on PATH. If `python` isn't recognized, install it
from python.org and check "Add python.exe to PATH" during setup.

## Configuration you must fill in

Nothing here guesses at your specific pools. Before you'll get real
quotes, fill these into `.env` (or `config.py` directly):

- `MOOLAH_ADDRESS` — the token contract address
- `POOL_WBNB_MOOLAH`, `POOL_MOOLAH_USDT`, `POOL_USDT_WBNB` — the pool
  addresses for each hop (used to confirm you're targeting the pool you
  mean to; the quoter itself routes by token pair + fee tier)
- `FEE_WBNB_MOOLAH`, `FEE_MOOLAH_USDT`, `FEE_USDT_WBNB` — each pool's fee
  tier in hundredths of a bip (500 = 0.05%, 2500 = 0.25%, 3000 = 0.3%,
  10000 = 1%)
- `QUOTER_ADDRESS` / `ROUTER_ADDRESS` — defaults point at PancakeSwap V3's
  Quoter/SmartRouter on BSC mainnet; change these if your pools belong to
  a different V3-style fork

Tunable economics: `SCAN_SIZES_WBNB` (comma-separated list, smallest to
largest — the bot evaluates every size each pass, since a thin pool on
one leg can revert on a larger probe while still fitting a smaller one),
`SLIPPAGE_BUFFER_BPS`, `GAS_LIMIT_ESTIMATE`, `GAS_PRICE_BUFFER_MULT`,
`MIN_PROFIT_WBNB`, `POLL_INTERVAL_SECONDS`.

## Output

Every profitable pass appends a row to:

```
%USERPROFILE%\Documents\searcher_bot_opportunities.csv
```

(override with `CSV_PATH` in `.env`). Columns: timestamp, hop path, input
size, gross output, gross profit, slippage buffer, gas cost, net profit,
whether it cleared the execution threshold, and the simulation
status/detail. The file is flushed after every write, so you can tail it
live while the bot runs.

## Project layout

```
config.py       # all tunables: network, tokens, pools, fees, sizing, CSV path
abis.py         # minimal ABI fragments (QuoterV2, SwapRouter, ERC20)
dex.py          # web3 connection + get_quote() via eth_call
arbitrage.py    # path walking, gross/net profit math -> Opportunity
logger.py       # CSV append, flushed per row
simulator.py    # full-path eth_call simulation, optional state overrides
main.py         # polling loop, entry point
requirements.txt
.env.example
```

## Disclaimer

## Troubleshooting

**`quote reverted ... Unexpected error` / raw `0x08c379a0...` hex, at EVERY probe size**
If this happens across the entire `SCAN_SIZES_WBNB` range including your
smallest size, it's usually not a sizing problem at all -- it means the
specific V3 pool you configured for that hop has little or no active
liquidity (possibly abandoned, or a stale/duplicate pool for that pair,
with the real liquidity sitting in a *different* pool or even a different
DEX version). Check the pool's live liquidity on GeckoTerminal or DEX
Screener rather than assuming a search result from earlier is still
accurate -- pools for small/new tokens can be created, drained, or
superseded within days. The Moolah/USDT hop in this project hit exactly
this: the V3 pool at fee=10000 had ~$1.5K liquidity and reverted at every
size, while the real ~$148K market for that pair turned out to be a
PancakeSwap **V2** pool instead. This project now supports mixing V2 and
V3 hops in the same path (see `dex_version` in `config.PATH`) for exactly
this situation.

**`quote reverted ... Unexpected error`, at LARGER sizes only**
This is the more common case: the probe size is simply too large for that
pool's liquidity at the current tick. The bot scans multiple sizes
(`SCAN_SIZES_WBNB`) so a revert on the largest size doesn't block smaller
ones from being evaluated and logged.

**Address checksum errors**
`ValueError: Unknown format '0x...'` means the address is malformed —
usually one character short or long (must be exactly 40 hex characters
after `0x`). `dex.py`'s `_checksum_or_raise()` now catches this and tells
you which field and how many characters it found; re-copy the address
from a block explorer rather than retyping it.

This is unaudited example software provided for a development/research
project. It does not place trades or move funds on its own. If you
extend it to execute live, test extensively on a testnet/fork first,
understand the MEV and frontrunning risks of public mempool submission,
and make sure automated on-chain trading is permitted in your
jurisdiction and complies with any applicable regulations before running
it against real capital.
