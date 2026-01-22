/**
 * Portfolio Charts - Chart.js visualizations
 * Uses data embedded from Jekyll template
 */

// Dark theme colors matching site
const colors = {
  bg: '#0d1117',
  bgSecondary: '#161b22',
  bgCard: '#1c2128',
  text: '#e6edf3',
  textSecondary: '#8b949e',
  green: '#3fb950',
  red: '#f85149',
  blue: '#58a6ff',
  yellow: '#d29922',
  border: '#30363d',
  gridLines: 'rgba(48, 54, 61, 0.5)',
};

// Common chart options
const commonOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: false,
    },
    tooltip: {
      backgroundColor: colors.bgCard,
      titleColor: colors.text,
      bodyColor: colors.textSecondary,
      borderColor: colors.border,
      borderWidth: 1,
      padding: 12,
      cornerRadius: 8,
    },
  },
  scales: {
    x: {
      grid: {
        color: colors.gridLines,
        drawBorder: false,
      },
      ticks: {
        color: colors.textSecondary,
        maxRotation: 45,
        minRotation: 0,
      },
    },
    y: {
      grid: {
        color: colors.gridLines,
        drawBorder: false,
      },
      ticks: {
        color: colors.textSecondary,
      },
    },
  },
};

// Format currency
function formatCurrency(value) {
  return '$' + value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

// Format percentage
function formatPercent(value) {
  return (value * 100).toFixed(1) + '%';
}

// Initialize charts when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  if (typeof portfolioData === 'undefined') {
    console.error('Portfolio data not found');
    return;
  }

  createEquityChart();
  createDrawdownChart();
  createMonthlyReturnsChart();
});

// Equity Curve Chart
function createEquityChart() {
  const ctx = document.getElementById('equityChart');
  if (!ctx) return;

  const data = portfolioData.equity_curve;
  const labels = data.map(d => d.date);
  const values = data.map(d => d.value);

  new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Portfolio Value',
        data: values,
        borderColor: colors.green,
        backgroundColor: 'rgba(63, 185, 80, 0.1)',
        fill: true,
        tension: 0.1,
        pointRadius: 0,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: colors.green,
        pointHoverBorderColor: colors.text,
        pointHoverBorderWidth: 2,
        borderWidth: 2,
      }],
    },
    options: {
      ...commonOptions,
      plugins: {
        ...commonOptions.plugins,
        tooltip: {
          ...commonOptions.plugins.tooltip,
          callbacks: {
            label: function(context) {
              return formatCurrency(context.parsed.y);
            },
          },
        },
      },
      scales: {
        ...commonOptions.scales,
        x: {
          ...commonOptions.scales.x,
          type: 'category',
          ticks: {
            ...commonOptions.scales.x.ticks,
            maxTicksLimit: 12,
          },
        },
        y: {
          ...commonOptions.scales.y,
          ticks: {
            ...commonOptions.scales.y.ticks,
            callback: function(value) {
              return formatCurrency(value);
            },
          },
        },
      },
      interaction: {
        mode: 'index',
        intersect: false,
      },
    },
  });
}

// Drawdown Chart
function createDrawdownChart() {
  const ctx = document.getElementById('drawdownChart');
  if (!ctx) return;

  const data = portfolioData.drawdown_series;
  const labels = data.map(d => d.date);
  const values = data.map(d => -d.drawdown * 100); // Negative for visual

  new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Drawdown',
        data: values,
        borderColor: colors.red,
        backgroundColor: 'rgba(248, 81, 73, 0.2)',
        fill: true,
        tension: 0.1,
        pointRadius: 0,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: colors.red,
        pointHoverBorderColor: colors.text,
        pointHoverBorderWidth: 2,
        borderWidth: 2,
      }],
    },
    options: {
      ...commonOptions,
      plugins: {
        ...commonOptions.plugins,
        tooltip: {
          ...commonOptions.plugins.tooltip,
          callbacks: {
            label: function(context) {
              return context.parsed.y.toFixed(1) + '%';
            },
          },
        },
      },
      scales: {
        ...commonOptions.scales,
        x: {
          ...commonOptions.scales.x,
          type: 'category',
          ticks: {
            ...commonOptions.scales.x.ticks,
            maxTicksLimit: 12,
          },
        },
        y: {
          ...commonOptions.scales.y,
          max: 0,
          ticks: {
            ...commonOptions.scales.y.ticks,
            callback: function(value) {
              return value.toFixed(0) + '%';
            },
          },
        },
      },
      interaction: {
        mode: 'index',
        intersect: false,
      },
    },
  });
}

// Monthly Returns Bar Chart
function createMonthlyReturnsChart() {
  const ctx = document.getElementById('monthlyReturnsChart');
  if (!ctx) return;

  const data = portfolioData.monthly_returns;
  const labels = data.map(d => d.month);
  const values = data.map(d => d.return * 100);

  // Color bars based on positive/negative
  const backgroundColors = values.map(v => v >= 0 ? colors.green : colors.red);
  const borderColors = values.map(v => v >= 0 ? colors.green : colors.red);

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Monthly Return',
        data: values,
        backgroundColor: backgroundColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      ...commonOptions,
      plugins: {
        ...commonOptions.plugins,
        tooltip: {
          ...commonOptions.plugins.tooltip,
          callbacks: {
            label: function(context) {
              const val = context.parsed.y;
              return (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
            },
          },
        },
      },
      scales: {
        ...commonOptions.scales,
        x: {
          ...commonOptions.scales.x,
          ticks: {
            ...commonOptions.scales.x.ticks,
            maxTicksLimit: 18,
          },
        },
        y: {
          ...commonOptions.scales.y,
          ticks: {
            ...commonOptions.scales.y.ticks,
            callback: function(value) {
              return value.toFixed(0) + '%';
            },
          },
        },
      },
    },
  });
}
