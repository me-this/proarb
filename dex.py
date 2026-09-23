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
from abis import QUOTER_V2_ABI, ERC20_ABI


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


@lru_cache(maxsize=8)
def get_erc20(token_address: str):
    w3 = get_web3()
    return w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)


class QuoteError(Exception):
    """Raised when a quote could not be obtained (bad pool, no liquidity, RPC error...)."""


def get_quote(token_in: str, token_out: str, fee: int, amount_in_wei: int) -> int:
    """
    Return the simulated output amount (in wei of token_out) for swapping
    `amount_in_wei` of token_in -> token_out through the given V3 fee tier.
    Raises QuoteError if the call reverts (e.g. no pool at that fee, or the
    trade would exhaust available liquidity).
    """
    quoter = get_quoter()
    params = {
        "tokenIn": Web3.to_checksum_address(token_in),
        "tokenOut": Web3.to_checksum_address(token_out),
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
        raise QuoteError(f"quote reverted for {token_in}->{token_out} fee={fee}: {exc}") from exc
    except Exception as exc:  # network errors, decoding errors, etc.
        raise QuoteError(f"quote failed for {token_in}->{token_out} fee={fee}: {exc}") from exc


def get_gas_price_wei() -> int:
    w3 = get_web3()
    return w3.eth.gas_price
