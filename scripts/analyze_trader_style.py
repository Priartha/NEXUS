from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def build_profile(input_csv: Path) -> dict:
    df = pd.read_csv(input_csv)
    df["amount"] = pd.to_numeric(df["Amount with GST"], errors="coerce").fillna(0.0)
    df["gst"] = pd.to_numeric(df["GST"], errors="coerce").fillna(0.0)
    df["date_clean"] = df["Date"].astype(str).str.replace(r" IST Asia/Kolkata$", "", regex=True)
    df["dt"] = pd.to_datetime(df["date_clean"], errors="coerce")
    df["hour"] = df["dt"].dt.hour

    cashflow = df[df["Transaction type"].eq("cashflow")].copy()
    wins = cashflow[cashflow["amount"] > 0]
    losses = cashflow[cashflow["amount"] < 0]
    trade_types = ["cashflow", "trading fees", "liquidation_fee", "funding"]
    trading = df[df["Transaction type"].isin(trade_types)].copy()
    hourly = cashflow.groupby("hour")["amount"].agg(["count", "sum"]).reset_index()
    hourly = hourly[hourly["count"] >= 3]

    high_hours = sorted(int(h) for h in hourly[(hourly["sum"] > 1.0)]["hour"].tolist())
    blocked_hours = sorted(int(h) for h in hourly[(hourly["sum"] < -0.5)]["hour"].tolist())
    reduced_hours = sorted(int(h) for h in hourly[(hourly["sum"].between(-0.5, 1.0, inclusive="both"))]["hour"].tolist())

    amounts = cashflow.sort_values("dt")["amount"].tolist()
    after_win = [amounts[i] for i in range(1, len(amounts)) if amounts[i - 1] > 0]
    after_loss = [amounts[i] for i in range(1, len(amounts)) if amounts[i - 1] < 0]

    fee_sum = float(df[df["Transaction type"].eq("trading fees")]["amount"].sum())
    cashflow_net = float(cashflow["amount"].sum())
    gross_wins = float(wins["amount"].sum())
    gross_losses = float(losses["amount"].sum())
    trading_net = float(trading["amount"].sum())

    return {
        "source": str(input_csv),
        "generated_from_rows": int(len(df)),
        "date_min": str(df["dt"].min()),
        "date_max": str(df["dt"].max()),
        "timezone": "Asia/Kolkata",
        "cashflow_summary": {
            "cashflow_count": int(len(cashflow)),
            "wins": int(len(wins)),
            "losses": int(len(losses)),
            "cashflow_win_rate": round(len(wins) / len(cashflow), 4) if len(cashflow) else 0,
            "cashflow_profit_factor": round(gross_wins / abs(gross_losses), 4) if gross_losses else 0,
            "cashflow_net": round(cashflow_net, 6),
            "avg_win": round(float(wins["amount"].mean()), 6) if len(wins) else 0,
            "avg_loss": round(float(losses["amount"].mean()), 6) if len(losses) else 0,
            "largest_win": round(float(wins["amount"].max()), 6) if len(wins) else 0,
            "largest_loss": round(float(losses["amount"].min()), 6) if len(losses) else 0,
        },
        "cost_summary": {
            "trading_fees": round(fee_sum, 6),
            "gst": round(float(df["gst"].sum()), 6),
            "funding": round(float(df[df["Transaction type"].eq("funding")]["amount"].sum()), 6),
            "liquidation_fees": round(float(df[df["Transaction type"].eq("liquidation_fee")]["amount"].sum()), 6),
            "net_trading_after_costs": round(trading_net, 6),
            "fee_to_cashflow_net": round(abs(fee_sum) / abs(cashflow_net), 4) if cashflow_net else 0,
            "fee_to_gross_win": round(abs(fee_sum) / gross_wins, 4) if gross_wins else 0,
        },
        "behavior_summary": {
            "avg_next_cashflow_after_win": round(sum(after_win) / len(after_win), 6) if after_win else 0,
            "avg_next_cashflow_after_loss": round(sum(after_loss) / len(after_loss), 6) if after_loss else 0,
            "win_rate_after_win": round(sum(1 for x in after_win if x > 0) / len(after_win), 4) if after_win else 0,
            "win_rate_after_loss": round(sum(1 for x in after_loss if x > 0) / len(after_loss), 4) if after_loss else 0,
        },
        "execution_profile": {
            "high_performance_hours": high_hours,
            "blocked_hours": blocked_hours,
            "reduced_size_hours": reduced_hours,
            "good_hour_confidence_delta": -0.03,
            "reduced_hour_confidence_delta": 0.04,
            "min_fee_edge_ratio": 3.0,
            "post_win_cooldown_minutes": 45,
            "risk_per_trade_pct": 0.0075,
        },
        "notes": [
            "Profile is based on exchange cashflow rows, not model-tagged signals.",
            "Use this as an execution/risk overlay; keep production readiness gated by backtest validation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a NEXUS trader style profile from a Delta transaction CSV.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/trader_style_profile.json"))
    args = parser.parse_args()

    profile = build_profile(args.input_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
