---
layout: default
title: Portfolio Visualization
---

<link rel="stylesheet" href="assets/css/portfolio.css">

# Portfolio Visualization

**Dataset:** {{ site.data.portfolio_state.dataset }} | **Last Updated:** {{ site.data.portfolio_state.generated_at | date: "%B %d, %Y" }}

[<- Back to Signals](index.html) | [Performance](performance.html) | [Research](research.html)

---

## Summary Metrics

<div class="metrics-grid">
  <div class="metric-card">
    <div class="metric-value positive">${{ site.data.portfolio_state.summary_metrics.final_value | round: 0 | replace: ".", "," }}</div>
    <div class="metric-label">Final Value</div>
  </div>
  <div class="metric-card">
    <div class="metric-value {% if site.data.portfolio_state.summary_metrics.total_return >= 0 %}positive{% else %}negative{% endif %}">{{ site.data.portfolio_state.summary_metrics.total_return | times: 100 | round: 1 }}%</div>
    <div class="metric-label">Total Return</div>
  </div>
  <div class="metric-card">
    <div class="metric-value {% if site.data.portfolio_state.summary_metrics.cagr >= 0 %}positive{% else %}negative{% endif %}">{{ site.data.portfolio_state.summary_metrics.cagr | times: 100 | round: 1 }}%</div>
    <div class="metric-label">CAGR</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{{ site.data.portfolio_state.summary_metrics.sharpe_ratio }}</div>
    <div class="metric-label">Sharpe Ratio</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{{ site.data.portfolio_state.summary_metrics.sortino_ratio }}</div>
    <div class="metric-label">Sortino Ratio</div>
  </div>
  <div class="metric-card">
    <div class="metric-value negative">-{{ site.data.portfolio_state.summary_metrics.max_drawdown | times: 100 | round: 1 }}%</div>
    <div class="metric-label">Max Drawdown</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{{ site.data.portfolio_state.summary_metrics.win_rate | times: 100 | round: 1 }}%</div>
    <div class="metric-label">Win Rate</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{{ site.data.portfolio_state.summary_metrics.profit_factor }}</div>
    <div class="metric-label">Profit Factor</div>
  </div>
</div>

---

## Equity Curve

<div class="chart-container">
  <canvas id="equityChart"></canvas>
</div>

---

## Drawdown

<div class="chart-container">
  <canvas id="drawdownChart"></canvas>
</div>

---

## Monthly Returns

<div class="chart-container chart-container-small">
  <canvas id="monthlyReturnsChart"></canvas>
</div>

---

## Current Holdings ({{ site.data.portfolio_state.current_holdings | size }})

<div class="table-container">
<table class="holdings-table">
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Entry Date</th>
      <th>Entry $</th>
      <th>Current $</th>
      <th>Shares</th>
      <th>Value</th>
      <th>P&L %</th>
      <th>Score</th>
    </tr>
  </thead>
  <tbody>
    {% for holding in site.data.portfolio_state.current_holdings limit:20 %}
    <tr>
      <td><strong>{{ holding.ticker }}</strong></td>
      <td>{{ holding.entry_date }}</td>
      <td>${{ holding.entry_price }}</td>
      <td>${{ holding.current_price }}</td>
      <td>{{ holding.shares }}</td>
      <td>${{ holding.current_value | round: 0 }}</td>
      <td class="{% if holding.pnl_pct >= 0 %}positive{% else %}negative{% endif %}">{% if holding.pnl_pct >= 0 %}+{% endif %}{{ holding.pnl_pct }}%</td>
      <td>{{ holding.score }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>

{% if site.data.portfolio_state.current_holdings.size > 20 %}
<p class="table-note">Showing top 20 of {{ site.data.portfolio_state.current_holdings | size }} holdings by value</p>
{% endif %}

---

## Recent Closed Trades

<div class="table-container">
<table class="trades-table">
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Entry</th>
      <th>Exit</th>
      <th>Days</th>
      <th>P&L %</th>
      <th>Exit Reason</th>
    </tr>
  </thead>
  <tbody>
    {% for trade in site.data.portfolio_state.closed_positions limit:15 %}
    <tr>
      <td><strong>{{ trade.ticker }}</strong></td>
      <td>{{ trade.entry_date }}</td>
      <td>{{ trade.exit_date }}</td>
      <td>{{ trade.holding_days }}</td>
      <td class="{% if trade.pnl_pct >= 0 %}positive{% else %}negative{% endif %}">{% if trade.pnl_pct >= 0 %}+{% endif %}{{ trade.pnl_pct }}%</td>
      <td><span class="exit-badge exit-{{ trade.exit_reason }}">{{ trade.exit_reason }}</span></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>

---

## Strategy Configuration

| Parameter | Value |
|-----------|-------|
| Initial Capital | ${{ site.data.portfolio_state.simulation_config.initial_capital | round: 0 }} |
| Holding Period | {{ site.data.portfolio_state.simulation_config.holding_period_days }} days |
| Stop Loss | {{ site.data.portfolio_state.simulation_config.stop_loss_pct | times: 100 }}% |
| Max Position | {{ site.data.portfolio_state.simulation_config.max_position_pct | times: 100 }}% |
| Max Positions | {{ site.data.portfolio_state.simulation_config.max_positions }} |
| Score Range | {{ site.data.portfolio_state.simulation_config.min_score }} - {{ site.data.portfolio_state.simulation_config.max_score }} |

---

*Data generated from backtested simulation. Past performance does not guarantee future results.*

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
<script>
// Embed the data from Jekyll
const portfolioData = {{ site.data.portfolio_state | jsonify }};
</script>
<script src="assets/js/portfolio-charts.js"></script>
