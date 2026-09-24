"""
Configuration for the triangular arbitrage searcher bot.

Edit the values below, or override them with environment variables / a .env
file (copy .env.example to .env). Nothing is wired to a real token by
accident -- you must fill in real, checksummed contract addresses for
MOOLAH and the three pools before the bot can produce real quotes.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
RPC_URL = os.getenv("RPC_URL", "https://bsc-dataseed.binance.org/")
CHAIN_ID = int(os.getenv("CHAIN_ID", "56"))  # BNB Smart Chain mainnet

# Address used as the "from" account for simulated (eth_call) swaps.
# No private key is needed to run in simulation mode -- this bot never
# signs or broadcasts a transaction. Only set PRIVATE_KEY if you later
# add your own execution layer on top of this, and keep it out of git
# (.env is listed in .gitignore).
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x000000000000000000000000000000000dEaD1")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# Whether simulate_full_path() should try eth_call with balance/allowance
# state overrides (lets you simulate as if WALLET_ADDRESS already held and
# approved the input token, without needing real funds). Not every RPC
# provider supports overrides -- see README. If unsupported, the bot falls
# back to the quoter-only simulation automatically.
USE_STATE_OVERRIDE_SIM = _bool("USE_STATE_OVERRIDE_SIM", True)

# ---------------------------------------------------------------------------
# Tokens (checksummed addresses) -- fill in the real ones for your path
# ---------------------------------------------------------------------------
TOKENS = {
    "WBNB": os.getenv("WBNB_ADDRESS", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
    "MOOLAH": os.getenv("MOOLAH_ADDRESS", "0xbAb528425Edb1E0E36D3719bc3307d9C8ccE8888"),
    "USDT": os.getenv("USDT_ADDRESS", "0x55d398326f99059fF775485246999027B3197955"),
}

TOKEN_DECIMALS = {
    "WBNB": 18,
    "MOOLAH": int(os.getenv("MOOLAH_DECIMALS", "18")),
    "USDT": 18,
}

# ---------------------------------------------------------------------------
# Pools for the triangular path WBNB -> MOOLAH -> USDT -> WBNB.
# `fee` is in hundredths of a bip (V3 convention): 100 = 0.01%, 500 = 0.05%,
# 2500 = 0.25%, 3000 = 0.3%, 10000 = 1%. Set the real fee tier per pool.
# ---------------------------------------------------------------------------
PATH = [
    {
        "name": "WBNB/Moolah V3",
        "token_in": "WBNB",
        "token_out": "MOOLAH",
        "dex_version": "v3",
        "pool": os.getenv("POOL_WBNB_MOOLAH", "0x0459f493Ae6cE91953012097Ce24f7C851A697C9"),
        "fee": int(os.getenv("FEE_WBNB_MOOLAH", "2500")),  # 0.25% tier
    },
    {
        # The V3 Moolah/USDT pool (fee 10000) is a near-empty duplicate
        # (~$1.5K liquidity) that reverts on almost any probe size. The
        # real liquidity for this pair (~$148K) sits in a PancakeSwap V2
        # pool instead, so this hop routes there via the V2 Router's
        # getAmountsOut instead of the V3 Quoter. "pool" and "fee" are
        # informational only for a v2 hop -- the V2 router resolves the
        # pair itself and PancakeSwap V2's fee is a fixed 0.25%, not
        # configurable per pool.
        "name": "Moolah/USDT V2",
        "token_in": "MOOLAH",
        "token_out": "USDT",
        "dex_version": "v2",
        "pool": os.getenv("POOL_MOOLAH_USDT_V2", "0x6F06f821231e021950f6cBC49716f95b623D536f"),
        "fee": None,
    },
    {
        "name": "USDT/WBNB V3",
        "token_in": "USDT",
        "token_out": "WBNB",
        "dex_version": "v3",
        "pool": os.getenv("POOL_USDT_WBNB", "0x36696169C63e42cd08ce11f5deeBbCeBae652050"),
        "fee": int(os.getenv("FEE_USDT_WBNB", "500")),  # 0.05% tier
    },
]

# Router / Quoter contracts. Defaults point at PancakeSwap V3's Quoter/
# SmartRouter on BSC mainnet -- override if your pools belong to a
# different V3-style fork.
QUOTER_ADDRESS = os.getenv("QUOTER_ADDRESS", "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997")
ROUTER_ADDRESS = os.getenv("ROUTER_ADDRESS", "0x1b81D678ffb9C0263b24A97847620C99d213eB14")

# PancakeSwap V2 Router, used for any PATH hop with "dex_version": "v2".
ROUTER_V2_ADDRESS = os.getenv("ROUTER_V2_ADDRESS", "0x10ED43C718714eb63d5aA57B78B54704E256024E")

# ---------------------------------------------------------------------------
# Sizing & economics
# ---------------------------------------------------------------------------
# Thin, newly-created pools (like small-cap token pairs) can only absorb a
# small probe before the quoter runs out of liquidity/ticks and reverts.
# Rather than picking one fixed size and hoping it fits, the bot scans a
# list of sizes each pass and evaluates/logs whichever ones actually quote
# successfully. Give this as a comma-separated list, smallest to largest.
SCAN_SIZES_WBNB = [
    float(x) for x in os.getenv("SCAN_SIZES_WBNB", "0.001,0.005,0.01,0.05,0.1,0.5").split(",")
    if x.strip()
]
TRADE_SIZE_WBNB = float(os.getenv("TRADE_SIZE_WBNB", str(SCAN_SIZES_WBNB[0])))  # single-size fallback
SLIPPAGE_BUFFER_BPS = float(os.getenv("SLIPPAGE_BUFFER_BPS", "10"))   # 0.10% haircut
GAS_LIMIT_ESTIMATE = int(os.getenv("GAS_LIMIT_ESTIMATE", "550000"))   # 3 swaps, generous
GAS_PRICE_BUFFER_MULT = float(os.getenv("GAS_PRICE_BUFFER_MULT", "1.15"))  # +15% headroom
MIN_PROFIT_WBNB = float(os.getenv("MIN_PROFIT_WBNB", "0.0005"))       # execute-sim threshold

POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
# Every *profitable* opportunity (gross output > input) is appended here,
# no matter how small the margin -- there is no minimum-profit filter on
# logging, only on whether the bot goes on to run an execution simulation.
CSV_PATH = Path(os.getenv(
    "CSV_PATH",
    str(Path.home() / "Documents" / "searcher_bot_opportunities.csv"),
))
