"""Tiny browser front-end for the cookie recipe comparison.

Run:  python server.py
Then open http://127.0.0.1:8000

The page polls the save file, shows the two recipes side by side and lets you
pick the winner. Every pick is written back to the same save file, so the CLI
(cookies.py) can still be used afterwards.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cookies


LOCK = threading.Lock()
STATE_FILE = Path(cookies.AUTOSAVE)


def load_current():
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"No save file found at {STATE_FILE!r}. Run cookies.py first.")
    return cookies.load_state(STATE_FILE)


def recipe_payload(state, recipe_id, role):
    recipe = state["recipes"][recipe_id]
    proportions = cookies.normalize(recipe["values"])
    rows = []
    if proportions is not None:
        for item, proportion in zip(state["ingredients"], proportions):
            factor = cookies.conversion_factor(item)
            unit = "tsp" if factor == cookies.TSP_PER_CUP else "g"
            rows.append({
                "name": item["name"],
                "cups": f"{proportion:.5f}",
                "amount": cookies.format_amount(proportion, factor),
                "unit": unit,
            })
    return {
        "id": recipe_id,
        "role": role,
        "base_id": recipe["base_id"],
        "normalized": proportions is not None,
        "ingredients": rows,
    }


def state_payload(state):
    pending = state["pending_id"]
    payload = {
        "complete": pending is None,
        "generations": cookies.GENERATIONS,
        "completed": len(state["history"]),
        "winner_id": state["winner_id"],
        "pending_id": pending,
        "seed": state["seed"],
        "settings": state["settings"],
        "initial": recipe_payload(state, 0, "random initialization"),
        "final": recipe_payload(state, state["winner_id"], "final winner"),
        "history": state["history"],
    }
    if pending is not None:
        payload["winner"] = recipe_payload(state, state["winner_id"], "current winner")
        payload["competitor"] = recipe_payload(state, pending, "competitor")
    return payload


def select(winner_id):
    with LOCK:
        state = load_current()
        state = cookies.select_winner(state, winner_id)
        cookies.save_state(state, STATE_FILE)
        return state_payload(state)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, content_type):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
            return
        if path == "/state":
            try:
                with LOCK:
                    state = load_current()
                self._json(200, state_payload(state))
            except (OSError, ValueError) as error:
                self._json(500, {"error": str(error)})
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/select":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            winner_id = body.get("winner")
            if type(winner_id) is not int:
                raise ValueError("winner must be an integer recipe id")
            self._json(200, select(winner_id))
        except (OSError, ValueError) as error:
            self._json(400, {"error": str(error)})


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cookie Recipe Comparison</title>
<style>
  :root {
    --bg: #f6f7fb;
    --panel: #ffffff;
    --panel-2: #f2f4f8;
    --line: #e2e6ee;
    --text: #1c2330;
    --muted: #5d6675;
    --accent: #2f6fed;
    --win: #1a7f37;
    --warn: #9a6700;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: radial-gradient(1200px 600px at 50% -10%, #eaf0fb, var(--bg));
    color: var(--text);
    min-height: 100vh;
  }
  header {
    padding: 28px 32px 8px;
    max-width: 1200px;
    margin: 0 auto;
  }
  h1 { margin: 0 0 6px; font-size: 22px; font-weight: 650; letter-spacing: .2px; }
  .sub { color: var(--muted); font-size: 14px; }
  .progress {
    margin-top: 14px;
    height: 8px;
    border-radius: 999px;
    background: var(--panel-2);
    overflow: hidden;
  }
  .progress > div { height: 100%; background: linear-gradient(90deg, var(--accent), #7c5cff); transition: width .3s ease; }
  main { max-width: 1200px; margin: 0 auto; padding: 22px 32px 64px; }
  .meta { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0 22px; }
  .chip {
    background: var(--panel);
    border: 1px solid var(--line);
    color: var(--muted);
    padding: 7px 12px;
    border-radius: 999px;
    font-size: 13px;
  }
  .chip b { color: var(--text); font-weight: 600; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 820px) { .grid { grid-template-columns: 1fr; } main, header { padding-left: 18px; padding-right: 18px; } }
  .card {
    background: linear-gradient(180deg, var(--panel), var(--panel-2));
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    box-shadow: 0 10px 30px rgba(31,45,70,.08);
  }
  .card.head { outline: 1px solid rgba(47,111,237,.4); }
  .card-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
  .card h2 { margin: 0; font-size: 17px; font-weight: 650; }
  .badge {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .8px;
    padding: 4px 9px;
    border-radius: 999px;
    background: rgba(47,111,237,.1);
    color: var(--accent);
    border: 1px solid rgba(47,111,237,.3);
    white-space: nowrap;
  }
  .badge.next { background: rgba(154,103,0,.1); color: var(--warn); border-color: rgba(154,103,0,.3); }
  .base { color: var(--muted); font-size: 12.5px; margin: 2px 0 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: .6px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  tr:last-child td { border-bottom: none; }
  .amt { font-weight: 600; }
  .amt.tsp { color: #8a3fc7; }
  .amt.g { color: #1a7f37; }
  .empty { color: var(--muted); font-style: italic; }
  .actions { margin-top: 18px; }
  .pick {
    width: 100%;
    border: 1px solid rgba(26,127,55,.35);
    background: rgba(26,127,55,.09);
    color: var(--win);
    font: inherit;
    font-weight: 650;
    font-size: 15px;
    padding: 13px 16px;
    border-radius: 12px;
    cursor: pointer;
    transition: background .15s ease, transform .05s ease;
  }
  .pick:hover { background: rgba(26,127,55,.18); }
  .pick:active { transform: translateY(1px); }
  .pick:disabled { opacity: .5; cursor: default; }
  .done {
    background: linear-gradient(180deg, var(--panel), var(--panel-2));
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 22px;
  }
  .done h2 { margin: 0 0 6px; }
  .winner { color: var(--win); font-weight: 650; }
  .history { margin-top: 26px; }
  .history h2 { font-size: 16px; margin: 0 0 12px; color: var(--muted); font-weight: 600; }
  .hrow { display: flex; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 13.5px; }
  .hrow:last-child { border-bottom: none; }
  .hrow .g { color: var(--muted); min-width: 92px; }
  .hrow .w { color: var(--win); }
  .tfoot { margin-top: 26px; color: var(--muted); font-size: 12.5px; }
  .err { color: #b42318; background: rgba(180,35,24,.07); border: 1px solid rgba(180,35,24,.25); padding: 14px 16px; border-radius: 12px; }
  .loading { color: var(--muted); }
  .pulse { animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
</style>
</head>
<body>
<header>
  <h1>Cookie Recipe Comparison</h1>
  <div class="sub" id="sub">Loading&hellip;</div>
  <div class="progress"><div id="bar" style="width:0%"></div></div>
</header>
<main id="app"><div class="loading pulse">Loading recipe data&hellip;</div></main>

<script>
const app = document.getElementById('app');

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function chip(label, value) {
  return `<span class="chip">${esc(label)} <b>${esc(value)}</b></span>`;
}

function recipeCard(recipe, isWinner, disabled) {
  const badge = isWinner
    ? '<span class="badge">Current winner</span>'
    : '<span class="badge next">Competitor</span>';
  const base = recipe.base_id === null
    ? 'Base: none (random initialization)'
    : `Base: recipe ${recipe.base_id} + generation ${recipe.id} adjustments`;
  const rows = recipe.normalized
    ? recipe.ingredients.map(row => `
        <tr>
          <td>${esc(row.name)}</td>
          <td class="num">${esc(row.cups)} cups</td>
          <td class="num amt ${row.unit}">${esc(row.amount)}</td>
        </tr>`).join('')
    : '<tr><td colspan="3" class="empty">All raw weights are zero &mdash; cannot normalize.</td></tr>';
  return `
    <section class="card ${isWinner ? 'head' : ''}">
      <div class="card-top">
        <h2>Recipe ${recipe.id}</h2>
        ${badge}
      </div>
      <div class="base">${esc(base)}</div>
      <table>
        <thead>
          <tr><th>Ingredient</th><th class="num">Cups</th><th class="num">Amount</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="actions">
        <button class="pick" data-id="${recipe.id}" ${disabled ? 'disabled' : ''}>Pick recipe ${recipe.id}</button>
      </div>
    </section>`;
}

function historyBlock(history) {
  if (!history.length) return '';
  const rows = history.map(d => `
    <div class="hrow">
      <span class="g">Comparison ${d.generation}</span>
      <span>recipe ${d.base_id} vs recipe ${d.competitor_id}</span>
      <span class="w">&rarr; winner ${d.winner_id}</span>
    </div>`).join('');
  return `<section class="history"><h2>History</h2>${rows}</section>`;
}

function settingsChips(settings) {
  return [
    chip('Batch', settings.batch_size),
    chip('Cook time', settings.cook_time),
    chip('Cook temp', settings.cook_temperature),
  ].join('');
}

function render(state) {
  const total = state.generations;
  const completed = state.completed;
  const pct = Math.round((completed / total) * 100);
  document.getElementById('bar').style.width = pct + '%';

  if (state.complete) {
    document.getElementById('sub').textContent = `All ${total} comparisons complete. Final winner: recipe ${state.winner_id}.`;
    const finalCard = recipeCard(state.final, true, true);
    app.innerHTML = `
      <div class="done">
        <h2>Final winner: <span class="winner">recipe ${state.winner_id}</span></h2>
        <div class="sub">Seed ${esc(state.seed)} &middot; ${completed}/${total} comparisons</div>
      </div>
      <div class="meta">${settingsChips(state.settings)}</div>
      <div class="grid">${finalCard}</div>
      ${historyBlock(state.history)}
      <div class="tfoot">This run is finished. Start a new run with cookies.py if you want to compare again.</div>`;
    return;
  }

  document.getElementById('sub').textContent =
    `Comparison ${state.pending_id} of ${total} \u2014 pick the recipe that tastes better.` +
    ` (${completed} done)`;
  app.innerHTML = `
    <div class="meta">
      ${settingsChips(state.settings)}
      ${chip('Winner', 'recipe ' + state.winner_id)}
      ${chip('Seed', state.seed)}
    </div>
    <div class="grid" id="grid">
      ${recipeCard(state.winner, true, false)}
      ${recipeCard(state.competitor, false, false)}
    </div>
    ${historyBlock(state.history)}
    <div class="tfoot">Selection is saved automatically. The CLI (cookies.py) picks up right where this leaves off.</div>`;

  app.querySelectorAll('.pick').forEach(button => {
    button.addEventListener('click', () => choose(Number(button.dataset.id), button));
  });
}

async function choose(winner, button) {
  app.querySelectorAll('.pick').forEach(b => { b.disabled = true; });
  if (button) button.textContent = 'Saving\u2026';
  try {
    const response = await fetch('/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ winner }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save selection');
    render(data);
  } catch (error) {
    app.querySelectorAll('.pick').forEach(b => { b.disabled = false; });
    alert(error.message);
  }
}

async function refresh() {
  try {
    const response = await fetch('/state');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load state');
    render(data);
  } catch (error) {
    document.getElementById('sub').textContent = 'Error';
    app.innerHTML = `<div class="err">${esc(error.message)}</div>`;
  }
}

refresh();
setInterval(() => {
  if (!document.querySelector('.pick:disabled')) refresh();
}, 1500);
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Web UI for the cookie recipe comparison.")
    parser.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port to bind (default: 8000)")
    parser.add_argument("--file", default=str(cookies.AUTOSAVE), help="save file to use")
    args = parser.parse_args(argv)

    global STATE_FILE
    STATE_FILE = Path(args.file).expanduser()
    if not STATE_FILE.exists():
        print(f"No save file found at {STATE_FILE!r}. Run cookies.py first to create one.")
        return 1

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving {STATE_FILE} at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
