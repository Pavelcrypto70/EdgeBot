# EdgeBot

Bybit desk: скринер → **две MA-стратегии** (heavy / fast) → оптимизация по истории → **OOS proof** → whitelist → emulator.

## Публичный сайт (автономно, ПК может быть выключен)

Раз в **~1 час** GitHub Actions:
1. гоняет скан (кресты + Proof MA);
2. обновляет whitelist (добавляет / убирает);
3. пишет историю в `docs/data/`;
4. публикует GitHub Pages.

Ручной прогон:

```bash
python -m edgebot.cli autonomous --heavy 8 --fast 6
```

Сайт: `https://<user>.github.io/EdgeBot/` (после первого deploy).

## Локальный UI

Двойной клик: `ЗАПУСК_ЭКРАН.bat`  
Откроется `http://127.0.0.1:43123`

### Вкладки

1. **Скринер** — оборот / спред / 24h  
2. **Proof MA** — подбор EMA + проверка на out-of-sample  
3. **Whitelist / Emulator** — только монеты с доказанным краем

Кнопка **Proof MA → Whitelist** запускает полный цикл (несколько минут).

## Стратегии

| Bucket | Кого берём | MA |
|--------|------------|-----|
| **heavy** | majors + топ по обороту | медленные EMA + HTF filter |
| **fast** | остальные с крупной \|Δ 24h\| | быстрые EMA + pullback |

Параметры ищутся сеткой на train+OOS. В whitelist только если:
**WR ≥ 55%**, **≥ 8 сделок**, **E[R] ≥ 0**, **PF ≥ 1**, и на OOS **≥ 3 сделок** с **WR ≥ 55%** и **E[R] ≥ 0**.
Fast: EMA slow − fast ≥ 8, тейк ≥ 1.2R. Heavy/кресты: тейк ≥ 1.2R.

## CLI

```bat
.venv\Scripts\activate
edgebot proof --heavy 10 --fast 12
edgebot ui
```
