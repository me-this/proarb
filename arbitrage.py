"""
Core strategy logic.

Walks the configured swap path (e.g. WBNB -> Moolah -> USDT -> WBNB),
getting a live V3 quote for each hop. Because each quote is produced by
the pool's own quoter contract against real on-chain liquidity, DEX fees
and price impact for that hop are already embedded in the returned
amount -- we don't need to reimplement V3 tick math ourselves.

On top of the gross result we subtract:
  - a slippage buffer (basis points haircut, protects against the price
    moving between quoting and execution)
  - gas cost, converted into WBNB terms (gas on BNB Smart Chain is paid
    in native BNB, which is 1:1 redeemable with WBNB)

and only then compare against the minimum profit threshold.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

import config
from dex import get_quote, get_gas_price_wei, QuoteError


@dataclass
class HopResult:
    name: str
    token_in: str
    token_out: str
    fee: int
    amount_in: int   # wei
    amount_out: int  # wei


@dataclass
class Opportunity:
    timestamp: float
    amount_in_wbnb: float
    gross_amount_out_wbnb: float
    gross_profit_wbnb: float
    slippage_buffer_wbnb: float
    gas_cost_wbnb: float
    net_profit_wbnb: float
    hops: List[HopResult] = field(default_factory=list)
    is_gross_profitable: bool = False
    is_net_profitable: bool = False
    error: Optional[str] = None

    def hop_summary(self) -> str:
        return " -> ".join(h.name for h in self.hops)


def _to_wei(amount: float, decimals: int) -> int:
    return int(round(amount * (10 ** decimals)))


def _from_wei(amount: int, decimals: int) -> float:
    return amount / (10 ** decimals)


def evaluate_opportunity(trade_size_wbnb: Optional[float] = None) -> Opportunity:
    """
    Run one full pass of the configured path at the given trade size and
    return an Opportunity describing gross and net results. Never raises
    for ordinary quote failures -- those are captured on Opportunity.error
    so the caller can keep going (e.g. try the next size in a scan).
    """
    trade_size_wbnb = trade_size_wbnb if trade_size_wbnb is not None else config.TRADE_SIZE_WBNB
    wbnb_decimals = config.TOKEN_DECIMALS["WBNB"]
    amount_in_wei = _to_wei(trade_size_wbnb, wbnb_decimals)

    hops: List[HopResult] = []
    current_amount = amount_in_wei

    try:
        for step in config.PATH:
            token_in_addr = config.TOKENS[step["token_in"]]
            token_out_addr = config.TOKENS[step["token_out"]]
            if not token_in_addr or not token_out_addr:
                raise QuoteError(
                    f"Missing token address for hop {step['name']} "
                    f"({step['token_in']} -> {step['token_out']}); check config.py / .env"
                )
            if not step["pool"]:
                # The quoter routes by token pair + fee tier, not by pool
                # address directly, but we still require it configured so
                # you've confirmed the exact pool you intend to hit.
                raise QuoteError(f"Missing pool address for hop {step['name']}; check config.py / .env")

            amount_out = get_quote(token_in_addr, token_out_addr, step["fee"], current_amount)
            hops.append(HopResult(
                name=step["name"],
                token_in=step["token_in"],
                token_out=step["token_out"],
                fee=step["fee"],
                amount_in=current_amount,
                amount_out=amount_out,
            ))
            current_amount = amount_out

        gross_amount_out_wei = current_amount
        gross_amount_out_wbnb = _from_wei(gross_amount_out_wei, wbnb_decimals)
        gross_profit_wbnb = gross_amount_out_wbnb - trade_size_wbnb

        # Slippage buffer: haircut applied to the gross output to model
        # price movement between quoting and actual execution.
        slippage_buffer_wbnb = gross_amount_out_wbnb * (config.SLIPPAGE_BUFFER_BPS / 10_000)

        # Gas cost, converted to WBNB (1 BNB == 1 WBNB in value).
        gas_price_wei = get_gas_price_wei()
        buffered_gas_price_wei = int(gas_price_wei * config.GAS_PRICE_BUFFER_MULT)
        gas_cost_wei = buffered_gas_price_wei * config.GAS_LIMIT_ESTIMATE
        gas_cost_wbnb = _from_wei(gas_cost_wei, 18)  # native BNB is 18 decimals

        net_profit_wbnb = gross_profit_wbnb - slippage_buffer_wbnb - gas_cost_wbnb

        return Opportunity(
            timestamp=time.time(),
            amount_in_wbnb=trade_size_wbnb,
            gross_amount_out_wbnb=gross_amount_out_wbnb,
            gross_profit_wbnb=gross_profit_wbnb,
            slippage_buffer_wbnb=slippage_buffer_wbnb,
            gas_cost_wbnb=gas_cost_wbnb,
            net_profit_wbnb=net_profit_wbnb,
            hops=hops,
            is_gross_profitable=gross_profit_wbnb > 0,
            is_net_profitable=net_profit_wbnb > config.MIN_PROFIT_WBNB,
        )

    except QuoteError as exc:
        return Opportunity(
            timestamp=time.time(),
            amount_in_wbnb=trade_size_wbnb,
            gross_amount_out_wbnb=0.0,
            gross_profit_wbnb=0.0,
            slippage_buffer_wbnb=0.0,
            gas_cost_wbnb=0.0,
            net_profit_wbnb=0.0,
            hops=hops,
            is_gross_profitable=False,
            is_net_profitable=False,
            error=str(exc),
        )


def evaluate_opportunities(sizes_wbnb: Optional[List[float]] = None) -> List[Opportunity]:
    """
    Run evaluate_opportunity() across a list of probe sizes (smallest to
    largest, per config.SCAN_SIZES_WBNB by default) and return one
    Opportunity per size. Thin pools often revert on larger probes long
    before they revert on smaller ones -- scanning a range means the bot
    still finds and logs whatever size actually fits the shallowest pool
    on the path, instead of silently failing every pass because one fixed
    size happened to be too big.
    """
    sizes_wbnb = sizes_wbnb if sizes_wbnb is not None else config.SCAN_SIZES_WBNB
    return [evaluate_opportunity(size) for size in sizes_wbnb]
