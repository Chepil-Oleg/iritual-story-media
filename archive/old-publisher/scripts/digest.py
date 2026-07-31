#!/usr/bin/env python3
"""
Дайджест по сторис за период → Telegram 📊.

Режимы:
  python3 digest.py 3day   — последние 3 дня публикаций: выводы + стата
  python3 digest.py week   — последние 7 дней: общий вывод + метрики
  python3 digest.py all    — всё, что собрано (ретро)

Группирует записи метрик по ДАТЕ ПУБЛИКАЦИИ (из timestamp, KZT) — это надёжно
разделяет дни, даже если в одном файле метрик оказалось несколько историй.
Маппинг дата→день кампании захардкожен (CAL).

Конфиг (env приоритетнее, иначе .claude/secrets.env):
  METRICS_DIR, TELEGRAM_BOT_TOKEN, TG_REPORT_CHAT, TG_REPORT_THREAD
"""
import os, sys, json, glob, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_metrics as cm

# Календарь кампании: дата публикации → ярлык дня
CAL = {
    "2026-06-12": "Д1 Прижизненный (CTA)",
    "2026-06-13": "Д6 Зеркала",
    "2026-06-14": "Д5 Кремация 3 мифа (CTA)",
    "2026-06-15": "Д12 9 и 40 день",
    "2026-06-16": "Д7 Мусульмане (CTA)",
    "2026-06-17": "Д8 Три горсти",
    "2026-06-18": "Д9 Кремация не от чёрствости (CTA)",
    "2026-06-19": "Д15 Что клали",
    "2026-06-20": "Д11 Благоустройство (CTA)",
    "2026-06-21": "Д16 Наследство",
    "2026-06-22": "Д13 Без справки (CTA)",
}


def kz_date(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.datetime.strptime(ts, fmt)
            break
        except Exception:
            dt = None
    if dt is None:
        try:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    kz = dt.astimezone(datetime.timezone(datetime.timedelta(hours=5)))
    return kz.date().isoformat()


def load_all(metrics_dir):
    seen = {}
    for f in glob.glob(os.path.join(metrics_dir, "*.json")):
        try:
            for r in json.load(open(f, encoding="utf-8")):
                seen[r["id"]] = r  # по id, дубли схлопываются
        except Exception:
            pass
    return list(seen.values())


def day_stats(records):
    records = [r for r in records if r.get("metrics")]
    records.sort(key=lambda r: r.get("timestamp") or "")
    reaches = [cm._val(r, "reach") for r in records]
    reaches = [x for x in reaches if x]
    comp = round(100 * reaches[-1] / reaches[0]) if len(reaches) >= 2 and reaches[0] else None
    return {
        "slides": len(records),
        "reach": reaches[0] if reaches else None,
        "completion": comp,
        "replies": sum(cm._val(r, "replies") or 0 for r in records),
        "profile_visits": sum(cm._val(r, "profile_visits") or 0 for r in records),
        "records": records,
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "3day"
    window = {"3day": 3, "week": 7, "all": None}.get(mode, 3)
    sec = cm.load_secrets()
    metrics_dir = cm.cfg(sec, "METRICS_DIR", str(cm.PROJECT / "ops" / "data" / "metrics"))
    recs = load_all(metrics_dir)

    groups = {}
    for r in recs:
        d = kz_date(r.get("timestamp"))
        if d:
            groups.setdefault(d, []).append(r)
    dates = sorted(groups.keys())
    if window:
        dates = dates[-window:]
    if not dates:
        print("нет данных для дайджеста")
        return

    title = {"3day": "📈 Дайджест за 3 дня", "week": "🗓 Недельный итог",
             "all": "📈 Ретро-разбор (всё собранное)"}.get(mode, "📈 Дайджест")
    period = f"{dates[0]} — {dates[-1]}" if len(dates) > 1 else dates[0]
    lines = [f"{title} ({period})", "", "По дням:"]

    stats_list = []
    for d in dates:
        st = day_stats(groups[d])
        stats_list.append((d, st))
        label = CAL.get(d, "?")
        if st["completion"] is not None:
            lines.append(f"• {d[5:]} {label}: охват {st['reach']}, досмотр {st['completion']}%, "
                         f"в профиль {st['profile_visits']}, ответы {st['replies']}")
        elif st["slides"]:
            lines.append(f"• {d[5:]} {label}: {st['slides']} слайд., цифры ещё зреют")
        else:
            lines.append(f"• {d[5:]} {label}: данных нет")

    # агрегат по дням, где есть досмотр
    valid = [(d, s) for d, s in stats_list if s["completion"] is not None]
    if valid:
        avg = round(sum(s["completion"] for _, s in valid) / len(valid))
        best = max(valid, key=lambda x: x[1]["completion"])
        worst = min(valid, key=lambda x: x[1]["completion"])
        tot_pv = sum(s["profile_visits"] for _, s in stats_list)
        tot_rep = sum(s["replies"] for _, s in stats_list)
        lines += ["", "Итоги периода:",
                  f"• Средний досмотр: {avg}%",
                  f"• Лучший: {CAL.get(best[0],'?')} ({best[1]['completion']}%)",
                  f"• Слабее всех: {CAL.get(worst[0],'?')} ({worst[1]['completion']}%)",
                  f"• Всего переходов в профиль: {tot_pv}, ответов в директ: {tot_rep}"]
        # простой вывод
        concl = []
        if best[1]["completion"] >= 65:
            concl.append(f"{CAL.get(best[0],'?').split('(')[0].strip()} держит внимание лучше всех — "
                         f"такой заход/тему стоит повторять.")
        if worst[1]["completion"] < 50:
            concl.append(f"{CAL.get(worst[0],'?').split('(')[0].strip()} проседает по досмотру — "
                         f"кандидат на переписывание хука.")
        if tot_rep == 0:
            concl.append("Ответов в директ пока нет — стоит усилить мягкий призыв «напишите».")
        if concl:
            lines += ["", "🧠 Вывод:"] + [f"• {c}" for c in concl]
    else:
        lines += ["", "(досмотр пока не считается — цифры ещё зреют, вернёмся в следующем дайджесте)"]

    if mode == "week":
        lines += ["", "(детальный качественный разбор — Аналитик в чате «анализ сторис»)"]

    # не шлём дайджест, если ни по одному дню нет зрелых данных
    if not any(s["completion"] is not None for _, s in stats_list):
        print("нет зрелых данных за период — дайджест не шлю")
        return

    text = "\n".join(lines)
    tg_token = cm.cfg(sec, "TELEGRAM_BOT_TOKEN")
    tg_chat = cm.cfg(sec, "TG_REPORT_CHAT")
    tg_thread = cm.cfg(sec, "TG_REPORT_THREAD")
    if tg_token and tg_chat:
        res = cm.tg_post(tg_token, tg_chat, tg_thread, text)
        print(f"📊 дайджест в Telegram: {'ok' if res.get('ok') else res}")
    else:
        print(text)


if __name__ == "__main__":
    main()
