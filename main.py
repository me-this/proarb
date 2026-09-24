"""
Searcher bot entry point.

Loop:
  1. Evaluate the configured triangular path (quote-based, reflects real
     pool depth/price impact per hop).
  2. If gross_profit > 0 (ANY size), append a row to the CSV in Documents
     -- logging has no minimum profit filter.
  3. If net_profit > MIN_PROFIT_WBNB, additionally run a full-path
     execution simulation (eth_call, no funds moved, nothing signed or
     broadcast) and record its result on the same row.
  4. Sleep, repeat. Never crashes the whole bot on a single bad iteration
     (RPC hiccup, reverted quote, etc.) -- errors are printed and logging
     continues on the next tick.

Run:  python main.py
Stop: Ctrl+C
"""

import sys
import time
import traceback

import config
from arbitrage import evaluate_opportunities
from logger import log_opportunity
from simulator import simulate_full_path


def _print_startup_banner():
    print("=" * 72)
    print("Triangular Arbitrage Searcher Bot (simulation-only)")
    print("=" * 72)
    print(f"RPC:                {config.RPC_URL}")
    print(f"Path:               {' -> '.join(step['name'] for step in config.PATH)}")
    print(f"Scan sizes:         {', '.join(str(s) for s in config.SCAN_SIZES_WBNB)} WBNB")
    print(f"Slippage buffer:    {config.SLIPPAGE_BUFFER_BPS} bps")
    print(f"Min profit to sim:  {config.MIN_PROFIT_WBNB} WBNB")
    print(f"Poll interval:      {config.POLL_INTERVAL_SECONDS}s")
    print(f"CSV log:            {config.CSV_PATH}")
    print("This bot only SIMULATES execution -- it never signs or sends a real transaction.")
    print("=" * 72)
    missing = [k for k, v in config.TOKENS.items() if not v]
    missing_pools = [step["name"] for step in config.PATH if not step["pool"]]
    if missing or missing_pools:
        print("WARNING: incomplete configuration detected:")
        if missing:
            print(f"  missing token address(es): {', '.join(missing)}")
        if missing_pools:
            print(f"  missing pool address(es) for: {', '.join(missing_pools)}")
        print("  Fill these in via .env or config.py before expecting real quotes.")
        print("=" * 72)


def run_once() -> None:
    opportunities = evaluate_opportunities()  # one per size in config.SCAN_SIZES_WBNB
    any_quoted = False

    for opp in opportunities:
        if opp.error:
            # Common and expected for thin pools: a larger probe size can
            # revert (insufficient liquidity) while a smaller one succeeds.
            # We only print it, we don't stop the scan.
            print(f"[{time.strftime('%H:%M:%S')}] size={opp.amount_in_wbnb} quote error: {opp.error}")
            continue

        any_quoted = True
        print(
            f"[{time.strftime('%H:%M:%S')}] {opp.hop_summary()} | "
            f"in={opp.amount_in_wbnb:.6f} WBNB out={opp.gross_amount_out_wbnb:.6f} WBNB | "
            f"gross={opp.gross_profit_wbnb:+.8f} net={opp.net_profit_wbnb:+.8f}"
        )

        if not opp.is_gross_profitable:
            continue  # nothing to log -- no arbitrage at this size

        sim_status, sim_detail = "not_run", ""
        if opp.is_net_profitable:
            print(f"    -> net profit {opp.net_profit_wbnb:.8f} WBNB clears threshold, simulating execution...")
            sim = simulate_full_path(opp)
            sim_status, sim_detail = sim.status, sim.detail
            print(f"    -> simulation: {sim_status} ({sim_detail})")

        csv_path = log_opportunity(opp, simulation_status=sim_status, simulation_detail=sim_detail)
        print(f"    -> logged to {csv_path}")

    if not any_quoted:
        print(f"[{time.strftime('%H:%M:%S')}] no size in SCAN_SIZES_WBNB quoted successfully this pass")


def main() -> None:
    _print_startup_banner()
    try:
        while True:
            try:
                run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                print("Unexpected error this iteration (continuing):")
                traceback.print_exc()
            time.sleep(config.POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
