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
        "pool": os.getenv("POOL_WBNB_MOOLAH", "0x0459f493Ae6cE91953012097Ce24f7C851A697C9"),
        "fee": int(os.getenv("FEE_WBNB_MOOLAH", "2500")),  # 0.25% tier
    },
    {
        "name": "Moolah/USDT V3",
        "token_in": "MOOLAH",
        "token_out": "USDT",
        "pool": os.getenv("POOL_MOOLAH_USDT", "0x1b0c9c9C77D7E596610A9537f4eED95EA5A5999A"),
        "fee": int(os.getenv("FEE_MOOLAH_USDT", "10000")),  # 1% tier
    },
    {
        "name": "USDT/WBNB V3",
        "token_in": "USDT",
        "token_out": "WBNB",
        "pool": os.getenv("POOL_USDT_WBNB", "0x36696169C63e42cd08ce11f5deeBbCeBae652050"),
        "fee": int(os.getenv("FEE_USDT_WBNB", "500")),  # 0.05% tier
    },
]

# Router / Quoter contracts. Defaults point at PancakeSwap V3's Quoter/
# SmartRouter on BSC mainnet -- override if your pools belong to a
# different V3-style fork.
QUOTER_ADDRESS = os.getenv("QUOTER_ADDRESS", "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997")
ROUTER_ADDRESS = os.getenv("ROUTER_ADDRESS", "0x1b81D678ffb9C0263b24A97847620C99d213eB14")

# ---------------------------------------------------------------------------
# Sizing & economics
# ---------------------------------------------------------------------------
TRADE_SIZE_WBNB = float(os.getenv("TRADE_SIZE_WBNB", "0.5"))          # probe notional
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
