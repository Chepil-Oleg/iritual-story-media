# iRitual Stories Publisher

Автопостинг Instagram Stories для @iritual_agent через Graph API.
Видео хранятся на публичной папке Я.Диска, скачиваются IG напрямую.

## Архитектура

1. **Видео-сторис** (mp4 15 сек, 1080×1920, с музыкой) лежат на Я.Диске:
   `<публичная_папка_smm>/dayNN/N_slug.mp4`
2. **Расписание** в `schedule.yml` (формат `YYYY-MM-DD: dayNN`).
3. **GitHub Actions** запускается ежедневно в 11:00 KZT (06:00 UTC):
   - Читает `schedule.yml` для сегодняшней даты
   - Если день назначен — запускает `scripts/publish_day.py`
   - Скрипт обращается к публичному API Я.Диска, получает прямые ссылки на mp4
   - Создаёт IG containers через Graph API → ждёт FINISHED → media_publish
4. **Ручной запуск:** Actions → Publish IG Stories → Run workflow → указать день.

## Секреты (Settings → Secrets and variables → Actions)

- `IG_USER_ID` — Instagram User ID
- `FB_PAGE_ACCESS_TOKEN` — бессрочный Page Access Token
- `YADISK_PUBLIC_URL` — публичная URL папки на Я.Диске (вида `https://disk.yandex.kz/d/...`)

## Добавить день в расписание

```yaml
# schedule.yml
2026-06-10: day05
```

Положить mp4 файлы в папку `smm/day05/` на Я.Диске (через приложение или веб).

## Ограничения

- **Link sticker** через Graph API не поддерживается — CTA-дни публикуются вручную
  через Meta Business Suite.
- Прямые ссылки Я.Диска временные (~15 минут) — выдаются на каждый запуск,
  Instagram скачивает сразу. Не кэшировать.
- Файлы на Я.Диске должны лежать в подпапках с именем `dayNN` (нижний регистр).
- Внутри dayNN — mp4 с префиксом порядкового номера (`1_*.mp4`, `2_*.mp4`...).
  Скрипт сортирует по имени.
