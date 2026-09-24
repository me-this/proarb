"""
Thin wrapper around web3.py for talking to the chain: connection handling,
and a `get_quote` helper that calls the V3 QuoterV2 contract with
`eth_call` (a read-only simulated call, no gas spent, nothing broadcast)
to get the *actual* amount a swap would output against current pool
liquidity. Because the quoter walks the real pool state, its output
already reflects price impact for the given size -- that is the model's
main source of "is this trade actually worth it" accuracy.
"""

from functools import lru_cache
from web3 import Web3
from web3.exceptions import ContractLogicError

import config
from abis import QUOTER_V2_ABI, ERC20_ABI, ROUTER_V2_ABI


@lru_cache(maxsize=1)
def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(config.RPC_URL, request_kwargs={"timeout": 15}))
    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to RPC endpoint: {config.RPC_URL}")
    return w3


@lru_cache(maxsize=1)
def get_quoter():
    w3 = get_web3()
    return w3.eth.contract(address=Web3.to_checksum_address(config.QUOTER_ADDRESS), abi=QUOTER_V2_ABI)


@lru_cache(maxsize=1)
def get_router_v2():
    w3 = get_web3()
    return w3.eth.contract(address=Web3.to_checksum_address(config.ROUTER_V2_ADDRESS), abi=ROUTER_V2_ABI)


@lru_cache(maxsize=8)
def get_erc20(token_address: str):
    w3 = get_web3()
    return w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)


class QuoteError(Exception):
    """Raised when a quote could not be obtained (bad pool, no liquidity, RPC error...)."""


def _checksum_or_raise(label: str, address: str) -> str:
    """
    Validate + checksum an address with a clear error message instead of
    the raw eth_utils traceback. Catches the most common cause of this
    failing: an address copy-pasted with a character missing or extra
    (must be exactly 40 hex chars after the 0x).
    """
    if not address:
        raise QuoteError(f"{label} address is empty; check config.py / .env")
    hex_part = address[2:] if address.lower().startswith("0x") else address
    if len(hex_part) != 40:
        raise QuoteError(
            f"{label} address '{address}' has {len(hex_part)} hex characters after "
            f"'0x', expected 40. It was likely truncated or mistyped when copied in "
            f"-- re-copy it from a block explorer (e.g. bscscan.com)."
        )
    try:
        return Web3.to_checksum_address(address)
    except Exception as exc:
        raise QuoteError(f"{label} address '{address}' is not a valid address: {exc}") from exc


def get_quote(token_in: str, token_out: str, fee: int, amount_in_wei: int) -> int:
    """
    Return the simulated output amount (in wei of token_out) for swapping
    `amount_in_wei` of token_in -> token_out through the given V3 fee tier.
    Raises QuoteError if the call reverts (e.g. no pool at that fee, or the
    trade would exhaust available liquidity).
    """
    quoter = get_quoter()
    params = {
        "tokenIn": _checksum_or_raise("token_in", token_in),
        "tokenOut": _checksum_or_raise("token_out", token_out),
        "amountIn": amount_in_wei,
        "fee": fee,
        "sqrtPriceLimitX96": 0,
    }
    try:
        # QuoterV2's quoteExactInputSingle is declared nonpayable but is
        # meant to be called via eth_call, never sent as a real tx.
        amount_out, _sqrt_after, _ticks_crossed, _gas_est = quoter.functions.quoteExactInputSingle(
            params
        ).call()
        return amount_out
    except ContractLogicError as exc:
        # QuoterV2 catches every revert from the underlying pool swap and
        # re-throws a generic "Unexpected error" -- in practice this is
        # almost always the swap running out of initialized ticks/liquidity
        # for the requested amountIn, i.e. the probe size is too large for
        # this pool. We can't recover the original reason (the quoter
        # swallows it), so we just label it clearly rather than surface the
        # raw ABI-encoded string.
        msg = str(exc)
        if "Unexpected error" in msg or "0x08c379a0" in msg:
            raise QuoteError(
                f"quote for {token_in}->{token_out} fee={fee} reverted (likely insufficient "
                f"liquidity for amountIn={amount_in_wei} wei -- try a smaller probe size)"
            ) from exc
        raise QuoteError(f"quote reverted for {token_in}->{token_out} fee={fee}: {exc}") from exc
    except Exception as exc:  # network errors, decoding errors, etc.
        raise QuoteError(f"quote failed for {token_in}->{token_out} fee={fee}: {exc}") from exc


def get_quote_v2(token_in: str, token_out: str, amount_in_wei: int) -> int:
    """
    Return the simulated output amount (in wei of token_out) for swapping
    `amount_in_wei` of token_in -> token_out through the PancakeSwap V2
    Router's getAmountsOut (constant-product AMM, fixed 0.25% fee already
    reflected in the returned amount). Used for any PATH hop with
    "dex_version": "v2".
    """
    router = get_router_v2()
    path = [_checksum_or_raise("token_in", token_in), _checksum_or_raise("token_out", token_out)]
    try:
        amounts = router.functions.getAmountsOut(amount_in_wei, path).call()
        return amounts[-1]
    except ContractLogicError as exc:
        raise QuoteError(
            f"v2 quote reverted for {token_in}->{token_out}: {exc} "
            f"(commonly: no direct pair, or pair has insufficient liquidity for amountIn={amount_in_wei})"
        ) from exc
    except Exception as exc:
        raise QuoteError(f"v2 quote failed for {token_in}->{token_out}: {exc}") from exc


def get_gas_price_wei() -> int:
    w3 = get_web3()
    return w3.eth.gas_price