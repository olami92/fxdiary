let equityChart = null;
let winLossChart = null;

document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  loadDashboardData();
  setupEventListeners();
});

async function loadDashboardData() {
  try {
    const [statsRes, tradesRes] = await Promise.all([
      fetch("/api/stats"),
      fetch("/api/trades")
    ]);

    const statsData = await statsRes.json();
    const tradesData = await tradesRes.json();

    renderStats(statsData.stats);
    renderSheetInfo(statsData.user);
    renderTrades(tradesData.trades);
    updateCharts(tradesData.trades, statsData.stats);

  } catch (err) {
    console.error("Failed to load dashboard data:", err);
  }
}

function renderStats(stats) {
  const pnlEl = document.getElementById("net-pnl");
  const winRateEl = document.getElementById("win-rate");
  const profitFactorEl = document.getElementById("profit-factor");
  const totalTradesEl = document.getElementById("total-trades");

  if (pnlEl) {
    const val = stats.total_net_pnl || 0;
    pnlEl.textContent = `${val >= 0 ? '+' : ''}$${Math.abs(val).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    pnlEl.className = `stat-value ${val >= 0 ? 'win' : 'loss'}`;
  }
  if (winRateEl) winRateEl.textContent = `${stats.win_rate}%`;
  if (profitFactorEl) profitFactorEl.textContent = stats.profit_factor;
  if (totalTradesEl) totalTradesEl.textContent = stats.total_trades;

  document.getElementById("avg-win").textContent = `+$${(stats.avg_win || 0).toFixed(2)}`;
  document.getElementById("avg-loss").textContent = `-$${(stats.avg_loss || 0).toFixed(2)}`;
  document.getElementById("max-dd").textContent = `-$${(stats.max_drawdown || 0).toFixed(2)}`;
  document.getElementById("best-symbol").textContent = stats.best_symbol || "N/A";
}

function renderSheetInfo(user) {
  const badge = document.getElementById("sheet-badge");
  if (!badge) return;

  if (user && user.google_sheet_id) {
    badge.innerHTML = `🟢 <b>Connected Sheet:</b> ${user.sheet_title || 'Google Sheet'}`;
    badge.className = "badge badge-win";
  } else {
    badge.innerHTML = `⚪ <b>No Sheet Linked</b> (Use Telegram Bot /connect_sheet)`;
    badge.className = "badge";
  }
}

function renderTrades(trades) {
  const tbody = document.getElementById("trades-tbody");
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text-secondary);">No trades logged yet. Upload an MT5 screenshot or add a manual trade!</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map((t, idx) => {
    const pnl = t.net_profit || 0;
    const pnlClass = pnl >= 0 ? "badge-win" : "badge-loss";
    const typeClass = t.trade_type === "BUY" ? "badge-buy" : "badge-sell";

    return `
      <tr>
        <td>#${t.ticket || t.id}</td>
        <td><b>${t.symbol}</b></td>
        <td><span class="badge ${typeClass}">${t.trade_type}</span></td>
        <td>${t.volume.toFixed(2)}</td>
        <td>${t.open_price} → ${t.close_price}</td>
        <td>${t.pips >= 0 ? '+' : ''}${t.pips} pips</td>
        <td><span class="badge ${pnlClass}">${pnl >= 0 ? '+' : ''}$${Math.abs(pnl).toFixed(2)}</span></td>
        <td>${t.close_time}</td>
      </tr>
    `;
  }).join("");
}

function initCharts() {
  const ctxEquity = document.getElementById("equityChart")?.getContext("2d");
  const ctxWinLoss = document.getElementById("winLossChart")?.getContext("2d");

  if (ctxEquity) {
    equityChart = new Chart(ctxEquity, {
      type: "line",
      data: {
        labels: [],
        datasets: [{
          label: "Cumulative PnL ($)",
          data: [],
          borderColor: "#10B981",
          backgroundColor: "rgba(16, 185, 129, 0.1)",
          borderWidth: 3,
          fill: true,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94A3B8" } },
          y: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94A3B8" } }
        }
      }
    });
  }

  if (ctxWinLoss) {
    winLossChart = new Chart(ctxWinLoss, {
      type: "doughnut",
      data: {
        labels: ["Wins", "Losses", "Break Even"],
        datasets: [{
          data: [0, 0, 0],
          backgroundColor: ["#10B981", "#EF4444", "#64748B"],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { color: "#F8FAFC", font: { size: 12 } } }
        }
      }
    });
  }
}

function updateCharts(trades, stats) {
  if (!trades) return;

  const sorted = [...trades].reverse();
  let cumulative = 0;
  const labels = ["Start"];
  const data = [0];

  sorted.forEach((t, i) => {
    cumulative += (t.net_profit || 0);
    labels.push(`Trade ${i + 1}`);
    data.push(cumulative);
  });

  if (equityChart) {
    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = data;
    equityChart.data.datasets[0].borderColor = cumulative >= 0 ? "#10B981" : "#EF4444";
    equityChart.data.datasets[0].backgroundColor = cumulative >= 0 ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)";
    equityChart.update();
  }

  if (winLossChart && stats) {
    winLossChart.data.datasets[0].data = [stats.wins || 0, stats.losses || 0, stats.breakeven || 0];
    winLossChart.update();
  }
}

function setupEventListeners() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");

  if (dropZone && fileInput) {
    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) handleFileUpload(e.target.files[0]);
    });

    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.style.borderColor = "#3B82F6";
    });

    dropZone.addEventListener("dragleave", () => {
      dropZone.style.borderColor = "var(--border-color)";
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.style.borderColor = "var(--border-color)";
      if (e.dataTransfer.files.length > 0) handleFileUpload(e.dataTransfer.files[0]);
    });
  }
}

async function handleFileUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  const statusEl = document.getElementById("upload-status");
  if (statusEl) statusEl.innerHTML = "⏳ Analyzing screenshot with AI...";

  try {
    const res = await fetch("/api/upload-screenshot", {
      method: "POST",
      body: formData
    });
    const data = await res.json();

    if (data.success && data.parsed_trades && data.parsed_trades.length > 0) {
      const trade = data.parsed_trades[0];
      // Save parsed trade
      await fetch("/api/trades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: trade.symbol,
          trade_type: trade.trade_type,
          volume: trade.volume,
          open_price: trade.open_price,
          close_price: trade.close_price,
          profit: trade.profit
        })
      });

      if (statusEl) statusEl.innerHTML = "✅ Trade extracted & saved!";
      loadDashboardData();
    } else {
      if (statusEl) statusEl.innerHTML = "⚠️ Could not parse screenshot. Enter trade manually!";
    }
  } catch (err) {
    console.error("Upload error:", err);
    if (statusEl) statusEl.innerHTML = "❌ Upload failed.";
  }
}
