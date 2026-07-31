#!/usr/bin/env python3
"""
Сбор инсайтов по ЖИВЫМ Instagram Stories + авто-выводы → Telegram 📊.

Сторис живут 24 часа — инсайты доступны только пока история жива,
поэтому скрипт запускается ЕЖЕДНЕВНО (в GitHub workflow, утром).
Бесплатно, только Graph API.

Снимает по каждой живой сторис: reach, replies, total_interactions, shares,
follows, profile_visits, views, navigation (tap_forward/back/exit, swipe_forward).
Считает авто-выводы: досмотр до конца, где теряем людей, сила хука, переходы в профиль.

Конфиг (env приоритетнее, иначе .claude/secrets.env):
  FB_PAGE_ACCESS_TOKEN | IG_ACCESS_TOKEN, IG_USER_ID
  METRICS_DIR, TELEGRAM_BOT_TOKEN, TG_REPORT_CHAT, TG_REPORT_THREAD
"""
import os, sys, json, datetime, urllib.request, urllib.parse, urllib.error, pathlib

PROJECT = pathlib.Path(__file__).resolve().parents[2]
SECRETS = PROJECT / ".claude" / "secrets.env"
LOG = PROJECT / "ops" / "logs" / "collect_metrics.log"
GRAPH = "https://graph.facebook.com/v21.0"

STORY_METRICS = ["reach", "replies", "total_interactions", "shares",
                 "follows", "profile_visits", "views"]


def load_secrets():
    sec = {}
    if SECRETS.exists():
        for line in open(SECRETS, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                sec[k] = v.strip().strip('"').strip("'")
    return sec


def cfg(secrets, key, default=None):
    return os.environ.get(key) or secrets.get(key) or default


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(msg)


def gget(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read().decode())}
        except Exception:
            return {"error": str(e)}


def tg_post(token, chat, thread, text):
    params = {"chat_id": chat, "text": text}
    if thread:
        params["message_thread_id"] = thread
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e)}


def fetch_metric(media_id, metric, token):
    params = {"metric": metric, "access_token": token}
    if metric == "navigation":
        params["breakdown"] = "story_navigation_action_type"
    url = f"{GRAPH}/{media_id}/insights?" + urllib.parse.urlencode(params)
    r = gget(url)
    if "error" in r:
        return None
    data = r.get("data", [])
    if not data:
        return None
    item = data[0]
    tv = item.get("total_value")
    if tv is not None:
        out = {"value": tv.get("value")}
        bd = tv.get("breakdowns") or []
        if bd:
            results = {}
            for b in bd:
                for res in b.get("results", []):
                    key = "/".join(res.get("dimension_values", []))
                    results[key] = res.get("value")
            if results:
                out["breakdown"] = results
        return out
    vals = item.get("values") or []
    if vals:
        return {"value": vals[0].get("value")}
    return None


def _val(rec, key):
    v = rec.get("metrics", {}).get(key)
    return v.get("value") if isinstance(v, dict) else None


def has_mature_data(records):
    """Данные созрели? Нужны ≥2 слайда с охватом и заметная аудитория.
    Свежевыложенная сторис (охват ~0) — НЕ шлём отчёт, цифры ещё зреют."""
    reaches = [_val(r, "reach") for r in records]
    reaches = [x for x in reaches if x]
    return len(reaches) >= 2 and max(reaches) >= 10


def summarize_line(rec):
    parts = []
    if _val(rec, "reach") is not None:
        parts.append(f"охват {_val(rec,'reach')}")
    nav = rec.get("metrics", {}).get("navigation", {})
    bd = nav.get("breakdown") if isinstance(nav, dict) else None
    if bd:
        nv = []
        for k, sym in (("tap_forward", "→"), ("tap_back", "←"),
                       ("tap_exit", "выход "), ("swipe_forward", "свайп ")):
            if bd.get(k) is not None:
                nv.append(f"{sym}{bd[k]}")
        if nv:
            parts.append("нав: " + " ".join(nv))
    if _val(rec, "replies"):
        parts.append(f"ответы {_val(rec,'replies')}")
    if _val(rec, "profile_visits"):
        parts.append(f"в профиль {_val(rec,'profile_visits')}")
    return ", ".join(parts) if parts else "нет данных"


def analyze(records):
    """Авто-выводы по последовательности слайдов одной сторис."""
    recs = [r for r in records if r.get("metrics")]
    recs.sort(key=lambda r: r.get("timestamp") or "")
    lines = []
    reaches = []
    for i, r in enumerate(recs, 1):
        rv = _val(r, "reach")
        if rv:
            reaches.append((i, rv))
    if len(reaches) >= 2:
        first, last = reaches[0][1], reaches[-1][1]
        comp = round(100 * last / first) if first else 0
        lines.append(f"• Досмотр до конца: ~{comp}% (охват {first}→{last})")
        if comp >= 70:
            lines.append("  → сильное удержание, история держит внимание")
        elif comp >= 45:
            lines.append("  → среднее удержание")
        else:
            lines.append("  → слабое удержание, теряем рано — усилить хук/начало")
        drops = []
        for k in range(1, len(reaches)):
            prev, cur = reaches[k - 1][1], reaches[k][1]
            if prev:
                drops.append((reaches[k - 1][0], reaches[k][0], round(100 * (prev - cur) / prev)))
        if drops:
            worst = max(drops, key=lambda d: d[2])
            if worst[2] >= 12:
                lines.append(f"• Слабое место: на переходе слайд {worst[0]}→{worst[1]} "
                             f"теряем {worst[2]}% — пересмотреть слайд {worst[0]}")
    if recs:
        nav = recs[0].get("metrics", {}).get("navigation", {})
        bd = nav.get("breakdown") if isinstance(nav, dict) else None
        if bd and bd.get("tap_exit") is not None:
            lines.append(f"• Хук (1-й слайд): выходов {bd.get('tap_exit')}, "
                         f"возвратов {bd.get('tap_back', 0)}")
        pv_last = _val(recs[-1], "profile_visits")
        if pv_last:
            lines.append(f"• С последнего слайда в профиль перешли: {pv_last}")
        tot = sum(_val(r, "replies") or 0 for r in recs)
        if tot:
            lines.append(f"• Ответов в директ за сторис: {tot}")
    return lines


def main():
    sec = load_secrets()
    token = cfg(sec, "FB_PAGE_ACCESS_TOKEN") or cfg(sec, "IG_ACCESS_TOKEN")
    ig = cfg(sec, "IG_USER_ID")
    if not token or not ig:
        log("❌ нет токена или IG_USER_ID")
        sys.exit(2)
    outdir = pathlib.Path(cfg(sec, "METRICS_DIR", str(PROJECT / "ops" / "data" / "metrics")))

    url = f"{GRAPH}/{ig}/stories?fields=id,media_type,media_product_type,timestamp,permalink&access_token={token}"
    r = gget(url)
    if "error" in r:
        log(f"❌ /stories: {r['error']}")
        sys.exit(3)
    stories = r.get("data", [])
    log(f"collect_metrics start — живых сторис: {len(stories)}")

    records = []
    for s in stories:
        rec = {"id": s["id"], "timestamp": s.get("timestamp"),
               "media_type": s.get("media_type"), "permalink": s.get("permalink"),
               "metrics": {}}
        for m in STORY_METRICS + ["navigation"]:
            val = fetch_metric(s["id"], m, token)
            if val is not None:
                rec["metrics"][m] = val
        records.append(rec)

    today = datetime.date.today().isoformat()
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"{today}.json"
    existing = {}
    if outfile.exists():
        try:
            for rec in json.load(open(outfile, encoding="utf-8")):
                existing[rec["id"]] = rec
        except Exception:
            pass
    for rec in records:
        existing[rec["id"]] = rec
    merged = list(existing.values())
    json.dump(merged, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"wrote {len(records)} живых сторис ({len(merged)} всего за день) → {outfile}")

    # отчёт в Telegram «Отчёты»: цифры + выводы
    tg_token = cfg(sec, "TELEGRAM_BOT_TOKEN")
    tg_chat = cfg(sec, "TG_REPORT_CHAT")
    tg_thread = cfg(sec, "TG_REPORT_THREAD")
    if tg_token and tg_chat and records and not has_mature_data(records):
        log("  ⏳ цифры ещё зреют (сторис свежая) — отчёт не шлю")
    elif tg_token and tg_chat and records:
        now_kz = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5))).strftime("%H:%M")
        lines = [f"📊 Сторис за {today} (снято {now_kz}, {len(records)} слайд.)", "", "Цифры:"]
        for i, rec in enumerate(sorted(records, key=lambda r: r.get('timestamp') or ''), 1):
            lines.append(f"{i}. {summarize_line(rec)}")
        verdicts = analyze(records)
        if verdicts:
            lines += ["", "🧠 Выводы:"] + verdicts
        lines += ["", "(глубокий разбор — Аналитик раз в неделю)"]
        res = tg_post(tg_token, tg_chat, tg_thread, "\n".join(lines))
        log(f"  📊 отчёт в Telegram: {'ok' if res.get('ok') else res}")


if __name__ == "__main__":
    main()
