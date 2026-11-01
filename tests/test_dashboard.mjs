import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/mi_fitness_mcp/web_assets/static/js/app.js', import.meta.url), 'utf8');

function dashboard(responses) {
  const elements = new Map();
  const toasts = [];
  const context = vm.createContext({
    localStorage: { getItem: () => null },
    document: {
      addEventListener() {},
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, { value: '', textContent: '--', innerHTML: '' });
        return elements.get(id);
      },
    },
    fetch: async (url) => {
      const path = new URL(url, 'http://localhost').pathname.replace(/^\/proxy/, '');
      const response = responses[path] || { status: 'ok', count: 0, data: [] };
      return { ok: response.statusCode !== 401, status: response.statusCode || 200, text: async () => JSON.stringify(response) };
    },
    performance: { now: () => 0 },
  });
  vm.runInContext(source, context);
  context.showToast = (title, message, type) => toasts.push({ title, message, type });
  context.updateInspectorHeader = () => {};
  context.renderJsonViewer = () => {};
  return { context, elements, toasts };
}

test('data endpoints expose rows while the inspector retains the response envelope', async () => {
  const { context } = dashboard({ '/api/summary': { status: 'ok', count: 1, data: [{ steps: 1234 }] } });
  const rows = await context.api('GET', '/api/summary');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].steps, 1234);
  assert.equal(vm.runInContext('state.lastResponse.count', context), 1);
});

test('overview uses backend field names and preserves a zero stress score', async () => {
  const { context, elements } = dashboard({
    '/api/summary': { data: [{ steps: 1234, active_kcal: 345, distance_m: 2500 }] },
    '/api/heart-rate': { data: [{ bpm: 65 }] },
    '/api/sleep': { data: [{ duration_minutes: 420 }] },
    '/api/spo2': { data: [{ spo2_pct: 98 }] },
    '/api/stress': { data: [{ stress_score: 0 }] },
  });
  await context.loadOverview();
  for (const [id, expected] of Object.entries({ statSteps: '1,234', statCalories: '345', statDistance: '2.50', statHr: '65', statSleep: '7.0', statSpo2: '98%', statStress: '0' })) {
    assert.equal(String(elements.get(id).textContent), expected, id);
  }
});

test('daily activity table renders the API response and units', async () => {
  const { context, elements } = dashboard({ '/api/summary': { data: [{ date: '2026-10-17', steps: 1234, active_kcal: 345, distance_m: 2500 }] } });
  await context.querySummary();
  const html = elements.get('summaryVisualContainer').innerHTML;
  assert.match(html, /1,234/);
  assert.match(html, /345 kcal/);
  assert.match(html, /2\.50 km/);
});

test('sleep timeline reads the stages returned by the API', async () => {
  const { context, elements } = dashboard({ '/api/sleep': { data: [{ stages: [{ stage: 'deep', minutes: 60 }, { stage: 'light', minutes: 120 }, { stage: 'rem', minutes: 30 }, { stage: 'awake', minutes: 30 }] }] } });
  await context.querySleep();
  const html = elements.get('sleepTimelineWrapper').innerHTML;
  assert.match(html, /深睡 60m \(25%\)/);
  assert.match(html, /浅睡 120m \(50%\)/);
});

test('metric charts render rows inside the API envelope', async () => {
  const { context, elements } = dashboard({ '/api/metric-series': { data: [{ date: '2026-10-17', value: 1234 }] } });
  await context.queryMetricSeries();
  assert.match(elements.get('metricChartContainer').innerHTML, /1,234/);
});

test('HTTP errors do not return a successful-looking payload to callers', async () => {
  const { context, toasts } = dashboard({ '/api/sync': { statusCode: 401, detail: 'Invalid API key' } });
  assert.equal(await context.api('POST', '/api/sync', {}), null);
  assert.equal(toasts.at(-1).type, 'error');
});

test('failed and partial synchronizations do not show a success toast', async () => {
  for (const [status, type] of [['error', 'error'], ['partial', 'warning']]) {
    const { context, toasts } = dashboard({ '/api/sync': { status, results: [] } });
    await context.triggerSync(false);
    assert.equal(toasts.at(-1).type, type, status);
    assert.equal(toasts.some(toast => toast.type === 'success'), false);
  }
});
