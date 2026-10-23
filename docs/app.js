async function loadJson(path) {
  const res = await fetch(path + "?t=" + Date.now());
  if (!res.ok) throw new Error(path + " " + res.status);
  return res.json();
}

function chips(list, cls) {
  if (!list || !list.length) return "<span class='chip'>—</span>";
  return list.map((s) => `<span class="chip ${cls}">${s}</span>`).join("");
}

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU", { timeZone: "UTC" }) + " UTC";
  } catch {
    return iso;
  }
}

function money(v, dig = 2) {
  const n = Number(v || 0);
  return (n >= 0 ? "+" : "") + n.toFixed(dig);
}

function renderTable(box, rows, heads, mapRow) {
  if (!rows || !rows.length) {
    box.innerHTML = "<div class='empty'>Пока пусто</div>";
    return;
  }
  const body = rows.map(mapRow).join("");
  box.innerHTML = `<table><thead><tr>${heads.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderWl(rows) {
  renderTable(
    document.getElementById("wlTable"),
    rows,
    ["Монета", "Стиль", "EMA", "Винрейт", "Сделок"],
    (r) => `<tr>
      <td class="sym">${r.symbol}</td>
      <td>${r.strategy || r.bucket || "—"}</td>
      <td>${r.ema_fast || "—"} / ${r.ema_slow || "—"}</td>
      <td class="wr">${Number(r.winrate_pct || 0).toFixed(0)}%</td>
      <td>${r.trades_n ?? "—"}</td>
    </tr>`
  );
}

function renderHist(items) {
  const box = document.getElementById("histList");
  if (!items || !items.length) {
    box.innerHTML = "<div class='empty'>Истории пока нет</div>";
    return;
  }
  box.innerHTML = [...items]
    .reverse()
    .slice(0, 10)
    .map(
      (h) => `<div class="hist-item">
        <div class="t">${fmtTs(h.ts)}</div>
        <div class="s">WL ${h.whitelist_n} · +${(h.added || []).length} · −${(h.removed || []).length}</div>
      </div>`
    )
    .join("");
}

function renderTrading(t) {
  if (!t) return;
  const eq = Number(t.equity_usdt || t.balance_start_usdt || 1000);
  const start = Number(t.balance_start_usdt || 1000);
  const eqEl = document.getElementById("kpiEq");
  eqEl.textContent = eq.toFixed(2) + " USDT";
  eqEl.classList.toggle("good", eq > start);
  eqEl.classList.toggle("bad", eq < start);

  document.getElementById("kpiWr").textContent = Number(t.winrate_pct || 0).toFixed(0) + "%";
  document.getElementById("kpiReal").textContent = money(t.realized_pnl) + " USDT";
  document.getElementById("kpiReal").className = "n " + (t.realized_pnl >= 0 ? "good" : "bad");
  document.getElementById("kpiUnreal").textContent = money(t.unrealized_pnl) + " USDT";
  document.getElementById("kpiUnreal").className = "n " + (t.unrealized_pnl >= 0 ? "good" : "bad");
  document.getElementById("kpiClosed").textContent = String(t.closed_n ?? 0);
  document.getElementById("kpiOpen").textContent = String(t.open_n ?? 0);
  document.getElementById("posHint").textContent = "обновлено " + fmtTs(t.updated_at);
  document.getElementById("tradeNote").textContent = t.note_ru || "";

  const o = t.order || {};
  document.getElementById("kpiOrder").textContent =
    `${o.notional_usdt || 300} USDT ×${o.leverage || 3}`;

  renderTable(
    document.getElementById("posTable"),
    t.open_positions || [],
    ["Монета", "Сторона", "Вход", "Марка", "PnL", "Плечо", "Маржа"],
    (p) => {
      const cls = p.pnl >= 0 ? "wr" : "bad";
      return `<tr>
        <td class="sym">${p.symbol}</td>
        <td>${p.side}</td>
        <td>${Number(p.entry).toPrecision(6)}</td>
        <td>${Number(p.mark).toPrecision(6)}</td>
        <td class="${cls}">${money(p.pnl)}</td>
        <td>${p.lev}</td>
        <td>${Number(p.margin).toFixed(2)}</td>
      </tr>`;
    }
  );

  renderTable(
    document.getElementById("closedTable"),
    (t.closed_trades || []).slice(0, 25),
    ["Монета", "Сторона", "PnL", "Причина"],
    (c) => `<tr>
      <td class="sym">${c.symbol}</td>
      <td>${c.side}</td>
      <td class="${c.win ? "wr" : "bad"}">${money(c.pnl)}</td>
      <td>${c.reason || "—"}</td>
    </tr>`
  );

  renderTable(
    document.getElementById("symTable"),
    t.by_symbol || [],
    ["Монета", "Сделок", "WR", "PnL", "EMA"],
    (s) => `<tr>
      <td class="sym">${s.symbol}</td>
      <td>${s.trades}</td>
      <td class="wr">${Number(s.winrate_pct).toFixed(0)}%</td>
      <td class="${s.pnl >= 0 ? "wr" : "bad"}">${money(s.pnl)}</td>
      <td>${s.ema}</td>
    </tr>`
  );

  const logs = t.logs || [];
  document.getElementById("tradeLogs").textContent = logs.length
    ? logs.slice(-25).join("\n")
    : "нет логов";
}

async function main() {
  try {
    const [live, history, trading] = await Promise.all([
      loadJson("data/live.json"),
      loadJson("data/history.json").catch(() => []),
      loadJson("data/trading.json").catch(() => null),
    ]);
    document.getElementById("statusPill").textContent =
      live.status === "ok" ? "онлайн · автоскан" : live.status || "ok";
    document.getElementById("updatedAt").textContent =
      "скан: " + fmtTs(live.updated_at) + (trading ? " · торговля: " + fmtTs(trading.updated_at) : "");
    document.getElementById("kpiWl").textContent = String(
      live.whitelist_n ?? (live.whitelist || []).length
    );
    document.getElementById("diffAdd").innerHTML = chips(live.last_added, "add");
    document.getElementById("diffRem").innerHTML = chips(live.last_removed, "rem");
    document.getElementById("scanHint").textContent =
      live.next_scan_hint_ru || "Скан ≈ каждые 4 часа";
    document.getElementById("wlHint").textContent = "run " + (live.run_id || "—");
    renderWl(live.whitelist || []);
    renderHist(Array.isArray(history) ? history : []);
    if (trading) renderTrading(trading);
    else {
      document.getElementById("kpiEq").textContent = "ждём книгу";
      document.getElementById("posTable").innerHTML =
        "<div class='empty'>trading.json ещё нет — появится после скана</div>";
    }
  } catch (err) {
    document.getElementById("statusPill").textContent = "нет данных";
    document.getElementById("wlTable").innerHTML =
      "<div class='empty'>Не удалось загрузить данные<br/>" + err + "</div>";
  }
}

main();
setInterval(main, 5 * 60 * 1000);
