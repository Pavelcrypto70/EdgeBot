// Свежие тики читаем с raw main (не ждём деплой Pages каждые 10 мин)
const RAW_DATA =
  "https://raw.githubusercontent.com/Pavelcrypto70/EdgeBot/main/docs/data/";

async function loadJsonUrl(url) {
  const res = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now(), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(url + " " + res.status);
  return res.json();
}

async function loadJson(name) {
  try {
    return await loadJsonUrl(RAW_DATA + name);
  } catch {
    return await loadJsonUrl("data/" + name);
  }
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

function wlRow(r) {
  return `<tr>
    <td class="sym">${r.symbol}</td>
    <td>${r.strategy || r.bucket || "—"}</td>
    <td>${r.ema_fast || "—"} / ${r.ema_slow || "—"}</td>
    <td class="wr">${Number(r.winrate_pct || 0).toFixed(0)}%</td>
    <td>${r.trades_n ?? "—"}</td>
  </tr>`;
}

function renderWlSection(title, cls, rows) {
  if (!rows.length) return "";
  const heads = ["Монета", "Стратегия", "EMA", "Винрейт", "Сделок"];
  return `<div class="wl-group ${cls}">
    <div class="wl-group-title">${title} · ${rows.length}</div>
    <table><thead><tr>${heads.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(wlRow).join("")}</tbody></table>
  </div>`;
}

function renderWl(rows) {
  const box = document.getElementById("wlTable");
  if (!rows || !rows.length) {
    box.innerHTML = "<div class='empty'>Пока пусто</div>";
    return;
  }
  const heavy = rows.filter((r) => r.bucket === "heavy");
  const fast = rows.filter((r) => r.bucket === "fast");
  const other = rows.filter((r) => r.bucket !== "heavy" && r.bucket !== "fast");
  const html =
    renderWlSection("Медленные", "heavy", heavy) +
    renderWlSection("Быстрые", "fast", fast) +
    renderWlSection("Прочие", "other", other);
  box.innerHTML = html || "<div class='empty'>Пока пусто</div>";
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
      (h) => {
        const hn = h.whitelist_heavy_n;
        const fn = h.whitelist_fast_n;
        const split =
          hn != null || fn != null ? ` · медл ${hn ?? 0} / быстр ${fn ?? 0}` : "";
        return `<div class="hist-item">
        <div class="t">${fmtTs(h.ts)}</div>
        <div class="s">WL ${h.whitelist_n}${split} · +${(h.added || []).length} · −${(h.removed || []).length}</div>
      </div>`;
      }
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

  const symRows = t.by_symbol || [];
  const symHeavy = symRows.filter((s) => s.bucket === "heavy");
  const symFast = symRows.filter((s) => s.bucket === "fast");
  const symOther = symRows.filter((s) => s.bucket !== "heavy" && s.bucket !== "fast");
  const symHeads = ["Монета", "Сделок", "WR", "PnL", "EMA"];
  const symMap = (s) => `<tr>
      <td class="sym">${s.symbol}</td>
      <td>${s.trades}</td>
      <td class="wr">${Number(s.winrate_pct).toFixed(0)}%</td>
      <td class="${s.pnl >= 0 ? "wr" : "bad"}">${money(s.pnl)}</td>
      <td>${s.ema}</td>
    </tr>`;
  const symBox = document.getElementById("symTable");
  if (!symRows.length) {
    symBox.innerHTML = "<div class='empty'>Пока пусто</div>";
  } else if (symHeavy.length || symFast.length) {
    const part = (title, cls, rows) => {
      if (!rows.length) return "";
      return `<div class="wl-group ${cls}">
        <div class="wl-group-title">${title} · ${rows.length}</div>
        <table><thead><tr>${symHeads.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${rows.map(symMap).join("")}</tbody></table>
      </div>`;
    };
    symBox.innerHTML =
      part("Медленные", "heavy", symHeavy) +
      part("Быстрые", "fast", symFast) +
      part("Прочие", "other", symOther);
  } else {
    renderTable(symBox, symRows, symHeads, symMap);
  }

  const logs = t.logs || [];
  document.getElementById("tradeLogs").textContent = logs.length
    ? logs.slice(-25).join("\n")
    : "нет логов";
}

async function main() {
  try {
    const [live, history, trading] = await Promise.all([
      loadJson("live.json"),
      loadJson("history.json").catch(() => []),
      loadJson("trading.json").catch(() => null),
    ]);
    document.getElementById("statusPill").textContent =
      live.status === "ok" ? "онлайн · автоскан" : live.status || "ok";
    document.getElementById("updatedAt").textContent =
      "скан: " + fmtTs(live.updated_at) + (trading ? " · торговля: " + fmtTs(trading.updated_at) : "");
    const wlAll = live.whitelist || [];
    const heavyN =
      live.whitelist_heavy_n ?? wlAll.filter((r) => r.bucket === "heavy").length;
    const fastN =
      live.whitelist_fast_n ?? wlAll.filter((r) => r.bucket === "fast").length;
    const wlN = live.whitelist_n ?? wlAll.length;
    document.getElementById("kpiWl").textContent = String(wlN);
    document.getElementById("kpiWlSub").textContent =
      heavyN || fastN ? `${heavyN} медл · ${fastN} быстр` : "";
    document.getElementById("diffAdd").innerHTML = chips(live.last_added, "add");
    document.getElementById("diffRem").innerHTML = chips(live.last_removed, "rem");
    document.getElementById("scanHint").textContent =
      live.next_scan_hint_ru ||
      "Whitelist ≈ каждый час · медленные и быстрые вместе · входы ≈ каждую ~1 мин";
    document.getElementById("wlHint").textContent =
      `медл ${heavyN} · быстр ${fastN} · run ${live.run_id || "—"}`;
    renderWl(wlAll);
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
setInterval(main, 60 * 1000);
