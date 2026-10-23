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
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", { timeZone: "UTC" }) + " UTC";
  } catch {
    return iso;
  }
}

function renderWl(rows) {
  const box = document.getElementById("wlTable");
  if (!rows || !rows.length) {
    box.innerHTML = "<div class='empty'>Whitelist пуст — ждём следующий скан</div>";
    return;
  }
  const body = rows
    .map((r) => {
      const wr = Number(r.winrate_pct || 0).toFixed(0);
      return `<tr>
        <td class="sym">${r.symbol}</td>
        <td>${r.strategy || r.bucket || "—"}</td>
        <td>${r.ema_fast || "—"} / ${r.ema_slow || "—"}</td>
        <td class="wr">${wr}%</td>
        <td>${r.trades_n ?? "—"}</td>
        <td>${r.verdict_short || r.verdict || "—"}</td>
      </tr>`;
    })
    .join("");
  box.innerHTML = `<table>
    <thead><tr>
      <th>Монета</th><th>Стиль</th><th>EMA</th><th>Винрейт</th><th>Сделок</th><th>Вердикт</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function renderHist(items) {
  const box = document.getElementById("histList");
  if (!items || !items.length) {
    box.innerHTML = "<div class='empty'>Истории пока нет</div>";
    return;
  }
  const html = [...items]
    .reverse()
    .slice(0, 12)
    .map((h) => {
      const add = (h.added || []).length;
      const rem = (h.removed || []).length;
      return `<div class="hist-item">
        <div class="t">${fmtTs(h.ts)}</div>
        <div class="s">WL ${h.whitelist_n} · +${add} · −${rem}</div>
      </div>`;
    })
    .join("");
  box.innerHTML = html;
}

async function main() {
  try {
    const [live, history] = await Promise.all([
      loadJson("data/live.json"),
      loadJson("data/history.json").catch(() => []),
    ]);
    document.getElementById("statusPill").textContent = live.status === "ok" ? "онлайн · автоскан" : live.status || "ok";
    document.getElementById("updatedAt").textContent = "обновлено: " + fmtTs(live.updated_at);
    document.getElementById("kpiWl").textContent = String(live.whitelist_n ?? (live.whitelist || []).length);
    document.getElementById("kpiAdd").textContent = "+" + (live.last_added || []).length;
    document.getElementById("kpiRem").textContent = "−" + (live.last_removed || []).length;
    const o = live.order || {};
    document.getElementById("kpiOrder").textContent =
      `${o.margin_usdt || 100}$×${o.leverage || 3}=${o.notional_usdt || 300}$`;
    document.getElementById("diffAdd").innerHTML = chips(live.last_added, "add");
    document.getElementById("diffRem").innerHTML = chips(live.last_removed, "rem");
    document.getElementById("scanHint").textContent =
      live.next_scan_hint_ru || "Скан ≈ каждые 4 часа на GitHub Actions";
    document.getElementById("wlHint").textContent = "run " + (live.run_id || "—");
    renderWl(live.whitelist || []);
    renderHist(Array.isArray(history) ? history : []);
  } catch (err) {
    document.getElementById("statusPill").textContent = "нет данных";
    document.getElementById("wlTable").innerHTML =
      "<div class='empty'>Не удалось загрузить data/live.json<br/>" + err + "</div>";
  }
}

main();
setInterval(main, 5 * 60 * 1000);
