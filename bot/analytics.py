import os
import datetime
from typing import List, Dict, Any, Tuple
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server environments
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

def calculate_stats(trades: List[Any]) -> Dict[str, Any]:
    """Calculate comprehensive trading performance analytics."""
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": 0.0,
            "total_net_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_drawdown": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "best_symbol": "N/A",
            "total_pips": 0.0
        }

    total_trades = len(trades)
    wins = 0
    losses = 0
    breakeven = 0
    
    gross_profit = 0.0
    gross_loss = 0.0
    total_net_pnl = 0.0
    total_pips = 0.0
    
    symbol_pnl: Dict[str, float] = {}
    pnl_history = []

    for t in trades:
        # Support dict or ORM object
        pnl = t.net_profit if hasattr(t, "net_profit") else t.get("net_profit", 0.0)
        pips = t.pips if hasattr(t, "pips") else t.get("pips", 0.0)
        sym = (t.symbol if hasattr(t, "symbol") else t.get("symbol", "N/A")).upper()

        total_net_pnl += pnl
        total_pips += pips
        pnl_history.append(pnl)

        symbol_pnl[sym] = symbol_pnl.get(sym, 0.0) + pnl

        if pnl > 0.001:
            wins += 1
            gross_profit += pnl
        elif pnl < -0.001:
            losses += 1
            gross_loss += abs(pnl)
        else:
            breakeven += 1

    win_rate = round((wins / total_trades) * 100, 1) if total_trades > 0 else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)
    avg_win = round(gross_profit / wins, 2) if wins > 0 else 0.0
    avg_loss = round(gross_loss / losses, 2) if losses > 0 else 0.0
    
    best_trade = round(max(pnl_history), 2) if pnl_history else 0.0
    worst_trade = round(min(pnl_history), 2) if pnl_history else 0.0

    # Max Drawdown
    cumulative = np.cumsum(pnl_history)
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_drawdown = round(float(np.max(drawdown)), 2) if len(drawdown) > 0 else 0.0

    # Best symbol by PnL
    best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else "N/A"

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": win_rate,
        "total_net_pnl": round(total_net_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": max_drawdown,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "best_symbol": best_symbol,
        "total_pips": round(total_pips, 1)
    }

def generate_equity_chart(trades: List[Any], output_path: str) -> bool:
    """Generate a sleek dark-themed Equity Curve PNG image."""
    if not trades:
        return False

    # Sort trades chronologically
    sorted_trades = sorted(
        trades,
        key=lambda x: x.close_time if hasattr(x, "close_time") and x.close_time else datetime.datetime.min
    )

    pnls = [t.net_profit if hasattr(t, "net_profit") else t.get("net_profit", 0.0) for t in sorted_trades]
    cumulative_pnl = np.cumsum([0] + pnls)
    trade_numbers = list(range(len(cumulative_pnl)))

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor('#0F172A') # Tailwind Slate 900
    ax.set_facecolor('#1E293B')       # Slate 800

    # Plot Equity Line
    line_color = '#10B981' if cumulative_pnl[-1] >= 0 else '#EF4444'
    ax.plot(trade_numbers, cumulative_pnl, color=line_color, linewidth=2.5, marker='o', markersize=4, label='Cumulative PnL ($)')
    ax.fill_between(trade_numbers, cumulative_pnl, 0, color=line_color, alpha=0.15)

    ax.axhline(0, color='#64748B', linestyle='--', linewidth=1, alpha=0.7)

    # Titles & Labels
    ax.set_title('Cumulative Equity Curve ($)', fontsize=14, fontweight='bold', color='#F8FAFC', pad=12)
    ax.set_xlabel('Trade Count', fontsize=10, color='#94A3B8')
    ax.set_ylabel('Net PnL ($)', fontsize=10, color='#94A3B8')
    
    ax.tick_params(colors='#94A3B8')
    ax.grid(True, linestyle=':', alpha=0.3, color='#475569')

    # Add final balance text box
    final_pnl = cumulative_pnl[-1]
    pnl_str = f"+${final_pnl:,.2f}" if final_pnl >= 0 else f"-${abs(final_pnl):,.2f}"
    ax.text(
        0.98, 0.92, f"Total PnL: {pnl_str}",
        transform=ax.transAxes,
        fontsize=11, fontweight='bold',
        color='#FFFFFF',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=line_color, alpha=0.8),
        horizontalalignment='right'
    )

    plt.tight_layout()
    plt.savefig(output_path, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    return True
