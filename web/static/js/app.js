let equityChart = null;
let winLossChart = null;
let currentTradesPage = 1;
let selectedPeriod = "WTD";
let chartTrades = [];
let dashboardStats = {};

document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  setupEventListeners();
  setTodayLabel();
  initializeDashboard();
});

async function initializeDashboard() {
  try {
    const telegramApp = window.Telegram?.WebApp;
    if (telegramApp?.initData) {
      telegramApp.ready();
      telegramApp.expand();
      const loginResponse = await fetch("/api/auth/telegram-miniapp", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: telegramApp.initData })
      });
      const user = await loginResponse.json();
      if (!loginResponse.ok) throw new Error(user.detail || "Telegram Mini App sign-in failed.");
      showDashboard(user);
      await loadDashboardData();
      return;
    }
    const response = await fetch("/api/auth/me");
    if (!response.ok) return showSignIn();
    showDashboard(await response.json());
    await loadDashboardData();
  } catch (err) {
    showSignIn("Unable to connect. Please refresh and try again.");
  }
}

window.onTelegramAuth = async function (telegramUser) {
  const errorEl = document.getElementById("signin-error");
  if (errorEl) errorEl.hidden = true;
  try {
    const response = await fetch("/api/auth/telegram", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(telegramUser)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Telegram sign-in failed.");
    showDashboard(result);
    await loadDashboardData();
  } catch (err) { showSignIn(err.message); }
};

function showSignIn(message = "") {
  document.getElementById("signin-screen").hidden = false;
  document.getElementById("dashboard-app").hidden = true;
  const errorEl = document.getElementById("signin-error");
  if (errorEl) { errorEl.textContent = message; errorEl.hidden = !message; }
}

function showDashboard(user) {
  document.getElementById("signin-screen").hidden = true;
  document.getElementById("dashboard-app").hidden = false;
  const name = user.first_name || user.username || "Trader";
  document.getElementById("greeting-name").textContent = name;
  document.getElementById("sidebar-name").textContent = name;
  document.getElementById("user-avatar").textContent = name.trim().charAt(0).toUpperCase() || "T";
}

function setTodayLabel() {
  document.getElementById("today-label").textContent = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date()).toUpperCase();
}

async function loadDashboardData(page = currentTradesPage) {
  try {
    const [statsRes, tradesRes] = await Promise.all([fetch("/api/stats"), fetch(`/api/trades?page=${page}`)]);
    if (statsRes.status === 401 || tradesRes.status === 401) return showSignIn();
    const statsData = await statsRes.json();
    const tradesData = await tradesRes.json();
    dashboardStats = statsData.stats || {};
    chartTrades = statsData.chart_trades || [];
    renderStats(dashboardStats, statsData.opening_capital || 0);
    currentTradesPage = tradesData.pagination.page;
    renderTrades(tradesData.trades, tradesData.pagination);
    updateCharts(chartTrades, dashboardStats);
  } catch (err) { console.error("Failed to load dashboard data:", err); }
}

function renderStats(stats, openingCapital) {
  const pnl = Number(stats.total_net_pnl || 0);
  const balance = Number(openingCapital || 0) + pnl;
  setMoney("net-pnl", pnl, true);
  setMoney("opening-capital", Number(openingCapital || 0));
  setMoney("account-balance", balance);
  document.getElementById("win-rate").textContent = `${Number(stats.win_rate || 0).toFixed(1)}%`;
  document.getElementById("total-trades").textContent = Number(stats.total_trades || 0).toLocaleString();
  document.getElementById("profit-factor").textContent = Number(stats.profit_factor || 0).toFixed(2);
  document.getElementById("donut-winrate").textContent = `${Number(stats.win_rate || 0).toFixed(0)}%`;
  document.getElementById("wins-count").textContent = Number(stats.wins || 0);
  document.getElementById("losses-count").textContent = Number(stats.losses || 0);
  document.getElementById("breakeven-count").textContent = Number(stats.breakeven || 0);
  document.getElementById("best-symbol").textContent = stats.best_symbol || "—";
}

function setMoney(id, value, signed = false) {
  const node = document.getElementById(id);
  node.textContent = `${signed && value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (signed) node.classList.toggle("negative", value < 0);
}

function renderTrades(trades, pagination) {
  const tbody = document.getElementById("trades-tbody");
  if (!trades?.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades in your journal yet. Your Telegram trade entries will appear here.</td></tr>';
  } else {
    tbody.innerHTML = trades.map((t) => {
      const pnl = Number(t.net_profit || 0), isOpen = t.status === "OPEN";
      const symbol = escapeHtml(t.symbol || "—"), type = escapeHtml(t.trade_type || "—");
      const date = isOpen ? "Open position" : (t.close_time || "—");
      return `<tr><td><span class="trade-symbol">${symbol}</span><span class="trade-ticket">#${escapeHtml(t.ticket || t.id)}</span></td><td><span class="badge ${isOpen ? "badge-open" : "badge-closed"}">${isOpen ? "OPEN" : "CLOSED"}</span></td><td><span class="badge ${type === "BUY" ? "badge-buy" : "badge-sell"}">${type}</span></td><td>${Number(t.volume || 0).toFixed(2)} lots</td><td>${escapeHtml(String(t.open_price ?? "—"))} <span class="muted-arrow">→</span> ${isOpen ? "Open" : escapeHtml(String(t.close_price ?? "—"))}</td><td>${isOpen ? "—" : `${Number(t.pips || 0) > 0 ? "+" : ""}${Number(t.pips || 0)} pips`}</td><td>${isOpen ? "—" : `<span class="${pnl >= 0 ? "pnl-positive" : "pnl-negative"}">${pnl >= 0 ? "+" : "−"}$${Math.abs(pnl).toFixed(2)}</span>`}</td><td>${escapeHtml(date)}</td></tr>`;
    }).join("");
  }
  const paginationEl = document.getElementById("trade-pagination");
  const infoEl = document.getElementById("trade-page-info");
  const prev = document.getElementById("trade-prev-page"), next = document.getElementById("trade-next-page");
  paginationEl.hidden = pagination.total_pages <= 1;
  infoEl.textContent = pagination.total_trades ? `Showing ${(pagination.page - 1) * pagination.page_size + 1}–${Math.min(pagination.page * pagination.page_size, pagination.total_trades)} of ${pagination.total_trades} · Page ${pagination.page} of ${pagination.total_pages}` : "No trades";
  prev.disabled = pagination.page <= 1;
  next.disabled = pagination.page >= pagination.total_pages;
}

function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }

function initCharts() {
  const ctx = document.getElementById("equityChart")?.getContext("2d");
  const donut = document.getElementById("winLossChart")?.getContext("2d");
  if (ctx) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, "rgba(34,162,73,.22)"); gradient.addColorStop(1, "rgba(34,162,73,0)");
    equityChart = new Chart(ctx, { type: "line", data: { labels: [], datasets: [{ data: [], borderColor: "#22a249", backgroundColor: gradient, borderWidth: 2.5, fill: true, tension: .38, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: "#22a249", pointHoverBorderColor: "#fff", pointHoverBorderWidth: 3 }] }, options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" }, plugins: { legend: { display: false }, tooltip: { displayColors: false, backgroundColor: "#171a17", padding: 11, callbacks: { label: (item) => ` ${item.parsed.y >= 0 ? "+" : "−"}$${Math.abs(item.parsed.y).toFixed(2)}` } } }, scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: "#989e96", maxTicksLimit: 7, font: { size: 9 } } }, y: { grid: { color: "#eff1ed", drawTicks: false }, border: { display: false, dash: [3, 4] }, ticks: { color: "#989e96", padding: 9, maxTicksLimit: 5, font: { size: 9 }, callback: (v) => `${v < 0 ? "−" : ""}$${Math.abs(v)}` } } } } });
  }
  if (donut) winLossChart = new Chart(donut, { type: "doughnut", data: { labels: ["Wins", "Losses", "Break even"], datasets: [{ data: [0, 0, 0], backgroundColor: ["#22a249", "#9a3651", "#dce0d9"], borderWidth: 0, hoverOffset: 5, spacing: 4, borderRadius: 4 }] }, options: { cutout: "77%", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: "#171a17", padding: 10 } } } });
}

function periodStart(period, now) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (period === "WTD") { const daysSinceMonday = (start.getDay() + 6) % 7; start.setDate(start.getDate() - daysSinceMonday); }
  if (period === "MTD") start.setDate(1);
  if (period === "YTD") { start.setMonth(0, 1); }
  return start;
}

function updateCharts(trades, stats) {
  const now = new Date(), start = periodStart(selectedPeriod, now);
  const filtered = trades.filter((trade) => {
    if (trade.status === "OPEN" || !trade.close_time) return false;
    const date = new Date(trade.close_time);
    return !Number.isNaN(date.getTime()) && date >= start && date <= now;
  }).sort((a, b) => new Date(a.close_time) - new Date(b.close_time));
  let cumulative = 0;
  const labels = [formatChartDate(start)], values = [0];
  filtered.forEach((trade) => { cumulative += Number(trade.net_profit || 0); labels.push(formatChartDate(new Date(trade.close_time))); values.push(Number(cumulative.toFixed(2))); });
  if (!filtered.length) { labels.push("Today"); values.push(0); }
  if (equityChart) { equityChart.data.labels = labels; equityChart.data.datasets[0].data = values; equityChart.update(); }
  const periodNames = { WTD: "Week to date", MTD: "Month to date", YTD: "Year to date" };
  const periodPnl = filtered.reduce((sum, trade) => sum + Number(trade.net_profit || 0), 0);
  setMoney("period-pnl", periodPnl, true);
  document.getElementById("period-caption").textContent = periodNames[selectedPeriod];
  if (winLossChart && stats) { winLossChart.data.datasets[0].data = [stats.wins || 0, stats.losses || 0, stats.breakeven || 0]; winLossChart.update(); }
}

function formatChartDate(date) { return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date); }

function setupEventListeners() {
  document.getElementById("trade-prev-page")?.addEventListener("click", () => { if (currentTradesPage > 1) loadDashboardData(currentTradesPage - 1); });
  document.getElementById("trade-next-page")?.addEventListener("click", () => loadDashboardData(currentTradesPage + 1));
  document.getElementById("logout-button")?.addEventListener("click", async () => { await fetch("/api/auth/logout", { method: "POST" }); showSignIn(); });
  document.querySelectorAll(".period-button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".period-button").forEach((item) => item.classList.toggle("active", item === button));
    selectedPeriod = button.dataset.period;
    updateCharts(chartTrades, dashboardStats);
  }));
  document.getElementById("edit-capital")?.addEventListener("click", async () => {
    const current = Number(document.getElementById("opening-capital").textContent.replace(/[^\d.-]/g, "")) || 0;
    const answer = window.prompt("Enter your opening account capital (USD):", current.toFixed(2));
    if (answer === null) return;
    const amount = Number(answer.replace(/,/g, ""));
    if (!Number.isFinite(amount) || amount < 0) { window.alert("Please enter a valid amount of zero or more."); return; }
    const response = await fetch("/api/account/opening-capital", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount }) });
    if (!response.ok) { window.alert("Could not save opening capital. Please try again."); return; }
    await loadDashboardData();
  });
}
