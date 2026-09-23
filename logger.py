"""
Append-only CSV logging of profitable opportunities.

Every call to log_opportunity() opens the file, writes one row, flushes
and closes -- so the file on disk is updated the moment an opportunity is
found, not just when the process exits. The file (and its parent
Documents folder) is created automatically on first use.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config
from arbitrage import Opportunity

FIELDNAMES = [
    "timestamp_utc",
    "path",
    "amount_in_wbnb",
    "gross_amount_out_wbnb",
    "gross_profit_wbnb",
    "slippage_buffer_wbnb",
    "gas_cost_wbnb",
    "net_profit_wbnb",
    "meets_execution_threshold",
    "simulation_status",
    "simulation_detail",
]


def _ensure_file(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def log_opportunity(
    opp: Opportunity,
    csv_path: Optional[Path] = None,
    simulation_status: str = "not_run",
    simulation_detail: str = "",
) -> Path:
    """
    Append one row for a profitable opportunity. Called for ANY opportunity
    with gross_profit_wbnb > 0, regardless of size -- there is no minimum
    profit filter on logging itself.
    """
    csv_path = csv_path or config.CSV_PATH
    _ensure_file(csv_path)

    row = {
        "timestamp_utc": datetime.fromtimestamp(opp.timestamp, tz=timezone.utc).isoformat(),
        "path": opp.hop_summary(),
        "amount_in_wbnb": f"{opp.amount_in_wbnb:.10f}",
        "gross_amount_out_wbnb": f"{opp.gross_amount_out_wbnb:.10f}",
        "gross_profit_wbnb": f"{opp.gross_profit_wbnb:.10f}",
        "slippage_buffer_wbnb": f"{opp.slippage_buffer_wbnb:.10f}",
        "gas_cost_wbnb": f"{opp.gas_cost_wbnb:.10f}",
        "net_profit_wbnb": f"{opp.net_profit_wbnb:.10f}",
        "meets_execution_threshold": opp.is_net_profitable,
        "simulation_status": simulation_status,
        "simulation_detail": simulation_detail,
    }

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(row)
        f.flush()

    return csv_path
