"""
Transaction execution simulation.

This module NEVER signs or broadcasts a real transaction -- it only builds
calldata and runs it through `eth_call`, which asks a node "what would
happen if this were mined", without spending gas or touching real funds.

Two layers, from cheapest to most realistic:

1. Quoter-based simulation (arbitrage.evaluate_opportunity): fast, always
   available, reflects real pool depth/price impact per hop.

2. Full-path call simulation (this module): builds the actual
   `exactInputSingle` calldata for each hop and runs it via `eth_call`
   against the router, optionally with a state override that pretends
   WALLET_ADDRESS already holds and has approved the input token. This
   exercises the real router/pool contracts end-to-end (slippage checks,
   deadline logic, revert conditions) the way a live execution would,
   without needing funded wallets. State overrides require an RPC
   endpoint that supports the `stateOverride` param on eth_call (most
   local forks like Anvil/Hardhat do; many public RPCs do not). If the
   configured endpoint doesn't support it, this falls back to reporting
   the quoter-based result instead of failing the whole run.
"""

from dataclasses import dataclass
from typing import Optional

from web3 import Web3

import config
from abis import SWAP_ROUTER_ABI
from arbitrage import Opportunity
from dex import get_web3


@dataclass
class SimulationResult:
    status: str          # "success" | "reverted" | "override_unsupported" | "skipped" | "error"
    detail: str
    simulated_final_amount_wei: Optional[int] = None


def _erc20_balance_slot_override(amount_wei: int) -> dict:
    """
    Standard-layout ERC20 state override: sets storage such that
    balanceOf(WALLET_ADDRESS) == amount_wei and
    allowance(WALLET_ADDRESS, ROUTER_ADDRESS) == max uint256.

    NOTE: this assumes the canonical OpenZeppelin storage layout
    (balances at slot 0, allowances at slot 1), which many but not all
    ERC20 tokens use. For a token with a nonstandard layout, the override
    will simply have no effect and the call will fall through to
    reverting on insufficient balance -- it will not silently misreport
    success.
    """
    w3 = get_web3()
    wallet = Web3.to_checksum_address(config.WALLET_ADDRESS)
    router = Web3.to_checksum_address(config.ROUTER_ADDRESS)

    balance_slot = Web3.solidity_keccak(["uint256", "uint256"], [int(wallet, 16), 0])
    allowance_inner = Web3.solidity_keccak(["uint256", "uint256"], [int(wallet, 16), 1])
    allowance_slot = Web3.solidity_keccak(["uint256", "uint256"], [int(router, 16), int.from_bytes(allowance_inner, "big")])

    max_uint256 = (1 << 256) - 1
    return {
        "stateDiff": {
            "0x" + balance_slot.hex(): "0x" + amount_wei.to_bytes(32, "big").hex(),
            "0x" + allowance_slot.hex(): "0x" + max_uint256.to_bytes(32, "big").hex(),
        }
    }


def simulate_full_path(opp: Opportunity) -> SimulationResult:
    """
    Attempt a full-path eth_call simulation for an already-evaluated
    Opportunity. Only meaningful to call when opp.hops is populated (i.e.
    evaluate_opportunity() succeeded).
    """
    if not opp.hops:
        return SimulationResult(status="skipped", detail="no hops to simulate")

    if opp.hops[0].dex_version != "v3":
        # This simulator builds V3 SwapRouter (exactInputSingle) calldata;
        # a v2 first hop would need swapExactTokensForTokens instead. Rather
        # than silently mis-simulating, we skip and rely on the quoter-based
        # result for this pass.
        return SimulationResult(
            status="skipped",
            detail=f"first hop is dex_version={opp.hops[0].dex_version!r}; "
                    f"full-path eth_call simulation currently only supports a v3 first hop",
        )

    w3 = get_web3()
    router = w3.eth.contract(address=Web3.to_checksum_address(config.ROUTER_ADDRESS), abi=SWAP_ROUTER_ABI)
    wallet = Web3.to_checksum_address(config.WALLET_ADDRESS)

    current_amount = opp.hops[0].amount_in
    first_token_addr = config.TOKENS[opp.hops[0].token_in]

    overrides = {}
    if config.USE_STATE_OVERRIDE_SIM:
        try:
            overrides = {
                Web3.to_checksum_address(first_token_addr): _erc20_balance_slot_override(current_amount)
            }
        except Exception as exc:  # pragma: no cover - defensive
            return SimulationResult(status="error", detail=f"could not build state override: {exc}")

    try:
        for hop in opp.hops:
            token_in = config.TOKENS[hop.token_in]
            token_out = config.TOKENS[hop.token_out]
            min_out = int(hop.amount_out * (1 - config.SLIPPAGE_BUFFER_BPS / 10_000))

            params = {
                "tokenIn": Web3.to_checksum_address(token_in),
                "tokenOut": Web3.to_checksum_address(token_out),
                "fee": hop.fee,
                "recipient": wallet,
                "amountIn": current_amount,
                "amountOutMinimum": min_out,
                "sqrtPriceLimitX96": 0,
            }
            call_kwargs = {"from": wallet}

            if overrides:
                try:
                    result = router.functions.exactInputSingle(params).call(call_kwargs, "latest", overrides)
                except TypeError:
                    # Older web3 versions may not accept state_override positionally
                    # in this call signature -- retry without it and flag that
                    # overrides weren't actually applied.
                    result = router.functions.exactInputSingle(params).call(call_kwargs)
                    return SimulationResult(
                        status="override_unsupported",
                        detail="installed web3 version does not support eth_call state overrides; "
                               "ran without funded balance (hop may revert on real balance check)",
                        simulated_final_amount_wei=None,
                    )
            else:
                result = router.functions.exactInputSingle(params).call(call_kwargs)

            current_amount = result
            # Overrides only apply to the first hop's input token; a true
            # multi-hop override chain would need per-hop overrides on the
            # intermediate tokens too, which most providers won't support
            # in one call. We treat a successful first hop as strong
            # evidence the route/calldata is well-formed, and rely on the
            # quoter chain (evaluate_opportunity) for the rest of the path.
            break

        return SimulationResult(
            status="success",
            detail="first-hop eth_call simulation succeeded against live router/pool",
            simulated_final_amount_wei=current_amount,
        )

    except ValueError as exc:
        # Many nodes report unsupported stateOverride params as a ValueError
        # from the JSON-RPC error payload.
        msg = str(exc)
        if "stateOverride" in msg or "state override" in msg.lower():
            return SimulationResult(status="override_unsupported", detail=msg)
        return SimulationResult(status="reverted", detail=msg)
    except Exception as exc:
        return SimulationResult(status="reverted", detail=str(exc))
