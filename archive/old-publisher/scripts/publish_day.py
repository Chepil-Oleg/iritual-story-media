#!/usr/bin/env python3
"""
Публикатор Instagram Stories через Graph API. Источник видео — Telegram.

manifest.json:
  {
    "_chat": "<group_chat_id>", "_thread": <topic_thread_id>,
    "day06": {"header": <msg_id>, "files": ["<file_id>", ...]},
    ...
  }
После успешной публикации скрипт пишет в Telegram-тему отметку «✅ Выложено…»
ответом на сообщение-заголовок дня.

Секреты: IG_USER_ID, FB_PAGE_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN
"""
import os, sys, time, json, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
TG = os.environ["TELEGRAM_BOT_TOKEN"]

GRAPH = "https://graph.facebook.com/v21.0"
TGAPI = f"https://api.telegram.org/bot{TG}"

DAY_TITLES = {
    "day06": "Д6 Зеркала", "day08": "Д8 Три горсти", "day12": "Д12 9 и 40 день",
    "day15": "Д15 Что клали", "day16": "Д16 Наследство",
}


def jget(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def gpost(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read().decode())}
        except Exception:
            return {"error": str(e)}


def tg_url(file_id):
    r = jget(f"{TGAPI}/getFile?file_id={urllib.parse.quote(file_id)}")
    if not r.get("ok"):
        print(f"❌ getFile: {r}", file=sys.stderr); sys.exit(3)
    fp = r["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{TG}/{fp}"


def mark_published(chat, thread, header, day, n):
    """Отметка в Telegram-теме, что день выложен."""
    kz = timezone(timedelta(hours=5))
    ts = datetime.now(kz).strftime("%d.%m %H:%M")
    title = DAY_TITLES.get(day, day)
    text = f"✅ Выложено в сторис @iritual_agent\n{title} · {n} слайдов · {ts} (авто)"
    params = {"chat_id": chat, "text": text}
    if thread:
        params["message_thread_id"] = thread
    if header:
        params["reply_to_message_id"] = header
    r = gpost(f"{TGAPI}/sendMessage", params)
    print(f"  🏷  отметка в Telegram: {'ok' if r.get('ok') else r}")


def main():
    day = sys.argv[1]
    manifest = json.load(open("manifest.json", encoding="utf-8"))
    entry = manifest.get(day)
    if not entry:
        print(f"❌ Нет {day} в manifest.json", file=sys.stderr); sys.exit(2)
    # поддержка старого формата (список) и нового (dict)
    if isinstance(entry, list):
        fids, header = entry, None
    else:
        fids, header = entry["files"], entry.get("header")
    chat = manifest.get("_chat")
    thread = manifest.get("_thread")
    print(f"📤 {day}: {len(fids)} слайдов")

    # 1. Свежие direct URL из Telegram
    urls = []
    for i, fid in enumerate(fids, 1):
        urls.append(tg_url(fid))
        print(f"  🔗 слайд {i} → Telegram URL ok")

    # 2. Контейнеры IG
    containers = []
    for i, url in enumerate(urls, 1):
        for a in range(3):
            r = gpost(f"{GRAPH}/{IG_USER_ID}/media", {
                "media_type": "STORIES", "video_url": url, "access_token": TOKEN})
            if r.get("id"):
                containers.append((i, r["id"])); print(f"  📦 слайд {i} → id={r['id']}"); break
            print(f"     retry {a+1}: {r}"); time.sleep(5)
        else:
            print(f"❌ контейнер для слайда {i}", file=sys.stderr); sys.exit(3)

    # 3. Ждём FINISHED
    print("⏳ Ждём FINISHED…")
    for i, cid in containers:
        for _ in range(60):
            r = jget(f"{GRAPH}/{cid}?fields=status_code&access_token={TOKEN}")
            sc = r.get("status_code")
            if sc == "FINISHED":
                print(f"  ✓ слайд {i}"); break
            if sc == "ERROR":
                print(f"  ✗ слайд {i}: ERROR {r}"); sys.exit(4)
            time.sleep(5)
        else:
            print(f"❌ таймаут FINISHED слайд {i}", file=sys.stderr); sys.exit(4)

    # 4. Публикация
    if os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes"):
        print("🟡 DRY_RUN: пропускаю media_publish и отметку.")
        print("✅ Тестовый прогон ок — Telegram отдал видео, IG принял и обработал.")
        return

    print("🚀 Публикую…")
    published = 0
    for i, cid in containers:
        r = gpost(f"{GRAPH}/{IG_USER_ID}/media_publish", {
            "creation_id": cid, "access_token": TOKEN})
        ok = bool(r.get("id"))
        if ok:
            published += 1
        print(f"  {'✓' if ok else '✗'} слайд {i}: {r}")
        time.sleep(3)
    print(f"✅ Готово ({published}/{len(containers)})")

    # 5. Отметка в Telegram только если всё выложилось
    if chat and published == len(containers) and published > 0:
        mark_published(chat, thread, header, day, published)


if __name__ == "__main__":
    main()
