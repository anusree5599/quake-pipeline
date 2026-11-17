"""Renders the processed summary into a single self-contained HTML page.

Charts use Chart.js and the map uses Leaflet, both loaded from a CDN, so the
page is one file that can be opened locally or served straight from a bucket.
"""

from __future__ import annotations

import html
import json

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Earthquake Activity Report</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --surface-0: #f4f4f2; --surface-1: #fcfcfb; --border: #e2e1dc;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #7a7974;
    --series-1: #2a78d6; --grid: #ebeae6;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-0: #111110; --surface-1: #1a1a19; --border: #2e2d2b;
      --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
      --series-1: #3987e5; --grid: #2a2928;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         background: var(--surface-0); color: var(--text-primary); }
  main { max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 0 0 12px; }
  .sub { color: var(--text-secondary); margin: 0 0 24px; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .kpi, .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; }
  .kpi { padding: 14px 16px; }
  .kpi .label { color: var(--text-secondary); font-size: 13px; }
  .kpi .value { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; margin-bottom: 16px; }
  .card { padding: 18px; }
  .card .note { color: var(--text-muted); font-size: 12px; margin-top: 8px; }
  .chart { position: relative; height: 260px; }
  #map { height: 420px; border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); }
  th { color: var(--text-secondary); font-weight: 500; }
  td.num, th.num { text-align: right; }
  a { color: var(--series-1); }
  footer { color: var(--text-muted); font-size: 12px; margin-top: 24px; }
  @media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
  <h1>Earthquake Activity Report</h1>
  <p class="sub">__SUBTITLE__</p>

  <section class="kpis" id="kpis"></section>

  <section class="grid">
    <div class="card"><h2>Earthquakes per day</h2><div class="chart"><canvas id="dailyCount"></canvas></div></div>
    <div class="card"><h2>Average magnitude per day</h2><div class="chart"><canvas id="dailyMag"></canvas></div></div>
  </section>

  <section class="grid">
    <div class="card"><h2>Events by magnitude band</h2><div class="chart"><canvas id="bands"></canvas></div></div>
    <div class="card"><h2>Events by depth class</h2><div class="chart"><canvas id="depth"></canvas></div>
      <p class="note">Most earthquakes are shallow, where the crust is brittle.</p></div>
  </section>

  <section class="card" style="margin-bottom:16px">
    <h2>Where they happened</h2>
    <div id="map"></div>
    <p class="note">Circle size scales with magnitude. Showing up to the 1,500 strongest events.</p>
  </section>

  <section class="grid">
    <div class="card"><h2>Most active regions</h2><table id="regions"></table></div>
    <div class="card"><h2>Strongest events</h2><table id="strongest"></table></div>
  </section>

  <section class="card">
    <h2>Data quality</h2>
    <table id="quality"></table>
  </section>

  <footer>Source: USGS Earthquake Hazards Program (earthquake.usgs.gov). __FOOTER__</footer>
</main>

<script id="report-data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('report-data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = n => Number(n).toLocaleString();
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// KPI tiles
const k = D.summary.kpis;
const tiles = [
  ['Total earthquakes', fmt(k.total_events)],
  ['Strongest', 'M ' + k.max_magnitude.toFixed(1)],
  ['Average magnitude', 'M ' + k.average_magnitude.toFixed(2)],
  ['M4.0 or larger', fmt(k.events_m4_plus)],
  ['Busiest region', esc(k.busiest_region)],
  ['Tsunami-flagged', fmt(k.tsunami_flagged)],
];
document.getElementById('kpis').innerHTML = tiles.map(([l, v]) =>
  `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('');

// Charts: one series each, so no legend; titles name the measure.
Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
Chart.defaults.color = css('--text-secondary');
const axes = (yTitle) => ({
  x: { grid: { display: false }, border: { color: css('--border') } },
  y: { beginAtZero: true, grid: { color: css('--grid') }, border: { display: false },
       title: { display: true, text: yTitle } },
});
const bar = (id, labels, values, yTitle) => new Chart(document.getElementById(id), {
  type: 'bar',
  data: { labels, datasets: [{ data: values, backgroundColor: css('--series-1'),
          borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: 'bottom', maxBarThickness: 48 }] },
  options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
             interaction: { mode: 'index', intersect: false }, scales: axes(yTitle) },
});
const daily = D.summary.daily;
bar('dailyCount', daily.map(d => d.date.slice(5)), daily.map(d => d.count), 'Events');
new Chart(document.getElementById('dailyMag'), {
  type: 'line',
  data: { labels: daily.map(d => d.date.slice(5)),
          datasets: [{ data: daily.map(d => d.avg_magnitude), borderColor: css('--series-1'),
                       backgroundColor: css('--series-1'), borderWidth: 2, pointRadius: 3, tension: 0.25 }] },
  options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
             interaction: { mode: 'index', intersect: false },
             scales: { ...axes('Magnitude'), y: { ...axes('Magnitude').y, beginAtZero: false } } },
});
bar('bands', D.summary.magnitude_bands.map(b => b.band), D.summary.magnitude_bands.map(b => b.count), 'Events');
bar('depth', D.summary.depth_classes.map(c => c.class.replace(')', '').split(' (')), D.summary.depth_classes.map(c => c.count), 'Events');

// Map
const map = L.map('map', { worldCopyJump: true }).setView([20, 0], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxZoom: 8, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
D.summary.map_points.forEach(([lat, lon, mag, place]) => {
  L.circleMarker([lat, lon], { radius: Math.max(2, mag * 1.6), color: css('--series-1'),
    weight: 1, fillOpacity: 0.35 }).bindTooltip(`M ${mag} — ${esc(place)}`).addTo(map);
});

// Tables
const table = (id, head, rows) => {
  document.getElementById(id).innerHTML =
    '<thead><tr>' + head.map(([h, n]) => `<th class="${n ? 'num' : ''}">${h}</th>`).join('') + '</tr></thead>' +
    '<tbody>' + rows.map(r => '<tr>' + r.map((c, i) => `<td class="${head[i][1] ? 'num' : ''}">${c}</td>`).join('') + '</tr>').join('') + '</tbody>';
};
table('regions', [['Region'], ['Events', 1], ['Avg M', 1], ['Max M', 1], ['Avg depth (km)', 1]],
  D.summary.top_regions.map(r => [esc(r.region), fmt(r.count), r.avg_magnitude.toFixed(2), r.max_magnitude.toFixed(1), r.avg_depth_km.toFixed(1)]));
table('strongest', [['Time (UTC)'], ['M', 1], ['Location'], ['Depth (km)', 1]],
  D.summary.strongest_events.map(e => [e.time_utc.replace('T', ' ').slice(0, 16),
    e.magnitude.toFixed(1), e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.place)}</a>` : esc(e.place),
    e.depth_km]));
const q = D.quality;
table('quality', [['Check'], ['Rows', 1]], [
  ['Features received from API', fmt(q.input_features)],
  ...Object.entries(q.dropped_by_reason).map(([r, n]) => ['Dropped: ' + r.replaceAll('_', ' '), fmt(n)]),
  ['Clean rows used in this report', fmt(q.clean_rows)],
]);
</script>
</body>
</html>
"""


def render_report(summary: dict, quality: dict, params: dict, run_id: str) -> str:
    k = summary.get("kpis", {})
    subtitle = (
        f"{k.get('total_events', 0):,} earthquakes of magnitude {params.get('min_magnitude')}+ "
        f"over the last {params.get('days')} day(s), "
        f"{(k.get('first_event_utc') or '')[:10]} to {(k.get('last_event_utc') or '')[:10]} (UTC)."
    )
    data = json.dumps({"summary": summary, "quality": quality}, separators=(",", ":"))
    data = data.replace("</", "<\\/")  # keep the JSON from closing the <script> tag
    return (
        TEMPLATE.replace("__SUBTITLE__", html.escape(subtitle))
        .replace("__FOOTER__", html.escape(f"Pipeline run {run_id}."))
        .replace("__DATA__", data)
    )
