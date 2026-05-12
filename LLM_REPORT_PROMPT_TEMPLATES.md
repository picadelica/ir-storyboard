# Промпт-шаблоны для эксперта · LLM Report Ingest

> Эти шаблоны эксперт копирует в нужный агент (ChatGPT Deep Research, Claude,
> Gemini, Perplexity) ДО того, как закажет исследование. Цель — чтобы выход
> агента был максимально пригоден для парсера ir-storyboard (см.
> `LLM_REPORT_INGEST_SPEC.md`). Не нужно их «улучшать ручным художеством» — чем
> ближе к шаблону, тем меньше потерь при парсинге.

---

## 0. Универсальная вводная (вставлять во все шаблоны)

```
Ты помогаешь подготовить материал для нарративной IR-матрицы (ir-storyboard).
Матрица состоит из 8 концентрических слоёв с тремя подсекциями каждый:

  L1 Founder Personal Story          (1.1 Origin & Childhood / 1.2 Values & Beliefs
                                       / 1.3 Fears, Dreams & Identity)
  L2 Founder Professional Story      (2.1 Path to expertise / 2.2 Founder role &
                                       motivation / 2.3 Co-founder dynamics)
  L3 Community Culture, Values, Stories (3.1 Attraction & Selection / 3.2 Shared
                                       life / 3.3 Investors & Partners)
  L4 Community Professional Experience (4.1 Expertise & Diversity / 4.2 Growth
                                       & Transformation / 4.3 Collective Failure
                                       Memory)
  L5 Clients — Stories               (5.1 Client's challenge & context / 5.2
                                       Moment of choice & trust / 5.3 Conflict &
                                       Honesty)
  L6 Product & Business              (6.1 Architecture of the solution / 6.2
                                       Philosophy of product decisions / 6.3
                                       Evolution of the product)
  L7 Social Impact Vision            (7.1 Vision of change / 7.2 Contradictions
                                       & Cost / 7.3 Legacy)
  L8 PEST Context                    (8.1 Historical moment / 8.2 Market &
                                       technology / 8.3 Policy & regulation)

ВАЖНО: ты НЕ заполняешь L1–L3 из web-источников. Их закрывают только живые
интервью. Если факт явно тянет в L1–L3 — выноси его в раздел "Open questions
for interview", не пытайся свернуть с веб-цитатой.
```

---

## 1. ChatGPT Deep Research / Agent

ChatGPT Deep Research нативно делает сноски `[N]` со списком URL в конце —
именно тот формат, который парсер ожидает по умолчанию (см. `Доработка
openClaw.docx`).

```
[вставить §0]

ЗАДАЧА. Подготовь deep-research отчёт по {{subject}}. Покрой следующие
секции — РОВНО в этом порядке и с РОВНО этими заголовками первого уровня:

  Обзор
  История и хронология
  Основатели и структура собственности
  Инвестиции и финансирование
  Технология и продукт
  Планы и дорожная карта
  Конкурентная среда
  Регуляторный и социальный контекст
  Open questions for interview

Правила цитирования:
  • после каждого утверждения ставь [N] — номерную сноску
  • один [N] = один URL; если на одну фразу нужно подтверждение из нескольких
    источников — пиши [3][7]
  • в конце документа — раздел "Источники", где для каждого [N] укажи:
      [N] <Title> — <Publisher> — <full URL>
  • не дублируй URL под разными [N]; если один и тот же источник нужен в
    нескольких местах — переиспользуй номер
  • дай только реальные URL, не сокращай через t.co/bit.ly

Что НЕ нужно делать:
  • не пиши секции «Выводы», «Мнение», «Что это значит»
  • не используй превосходные степени без цифры («крупнейшая», «лучшая»)
  • не сочиняй цитаты — если нет прямой речи в источнике, лучше парафраз
  • не уходи в личностные темы (детство, страхи, ценности фаундера) — они
    закрываются интервью, не вебом

Длина: 1500–3500 слов основного текста + список источников. Раздел Open
questions — bullet list из 5–10 вопросов.
```

---

## 2. Claude Research / Claude.ai с веб-поиском

Claude обычно ставит сноски как `(Source 1)` или просто как inline-ссылки.
Парсер пресета `claude_research.py` понимает оба варианта, но **попроси
явно** перейти на `[N]`-формат — это упрощает дедупликацию.

```
[вставить §0]

Подготовь исследование на {{subject}}, используя web search.

Структура — РОВНО эти секции в этом порядке:
  Overview
  History & Timeline
  Founders & Ownership Structure
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

Формат цитат — ОБЯЗАТЕЛЬНО `[N]` (квадратные скобки, число):
  • после каждого утверждения — `[N]`
  • в конце — раздел "Sources" с записями вида:
      [N] Title — Publisher — https://full.url

НЕ используй (Source 1), не пиши URL inline, не делай footnote-ы в скобках —
только нумерованный список в конце с маркерами `[N]`.

Не пиши секции "Conclusions" или "What this means" — только факты с
источниками. Если факт нельзя подтвердить веб-источником, выноси его в Open
Questions, не пытайся его утвердить.

Длина основного текста: 1500–3500 слов.
```

---

## 3. Perplexity / Perplexity Pages

Perplexity по умолчанию ставит надстрочные сноски и хранит сорсинг в боковой
панели. При экспорте в PDF/Markdown сноски конвертируются в `[N]` — это удобно
для парсера.

```
[вставить §0]

Создай Perplexity Page по теме {{subject}}.

Секции — строго в этом порядке (заголовки H2):
  Overview
  History & Timeline
  Founders & Ownership
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

В каждом абзаце — минимум одна сноска. Перед экспортом убедись, что в
"Sources" перечислены все ссылки с заголовком и URL. Не используй
"Conclusions" или "Recommendations" — только факты.

Если делаешь PDF-экспорт — он сам положит сноски как `[1] [2] ...` в конце.
Если экспортируешь Markdown — оставь номерной формат, не "footnote-style".

Длина: 2–4 страницы.
```

---

## 4. Gemini Deep Research

Gemini Deep Research отдаёт документ с боковой панелью sources. При экспорте в
Google Docs / PDF появляется блок ссылок в конце.

```
[вставить §0]

Запусти Deep Research по теме {{subject}}. Используй такую структуру:

  Overview
  History & Timeline
  Founders
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

Каждое утверждение — со сноской. При экспорте — убедись, что в выходном
документе есть раздел "Sources" с пронумерованным списком URL.

Не пиши "Conclusions" и "Implications" — только атомарные факты с
источниками. Если факт можно найти только в подкасте/интервью — указывай
URL подкаста (audio-источник), парсер пометит это как online_interview, а
не online_research.

Длина: 1500–3500 слов.
```

---

## 5. Опциональный «шаблон верификации»

Когда эксперт хочет, чтобы вторая LLM перепроверила факты ПЕРЕД заливкой в
матрицу. Помогает поймать галлюцинации Deep Research-агентов.

```
Вот отчёт по теме {{subject}}, собранный другим агентом (см. ниже). Твоя задача —
не дополнять и не переписывать, а аудировать:

1. Пройдись по каждой сноске [N]. Открой URL. Скажи:
   • открывается ли страница (200 OK)
   • есть ли на ней фраза, подтверждающая утверждение, к которому привязан [N]
   • если на странице другая редакция факта — выпиши дословно как есть

2. Найди утверждения, для которых на самом деле НЕТ источника в списке Sources
   (LLM иногда «забывает» поставить сноску). Перечисли их.

3. Найди утверждения, где источник есть, но он не подтверждает факт. Это
   галлюцинация или ошибка цитирования.

4. Дай таблицу:
   | claim | cite | url status | snippet found | verdict
   verdict ∈ {confirmed, partial, contradicted, not_found, dead_url}

НЕ дополняй новыми фактами и НЕ удаляй ничего из исходного отчёта. Только
аудит.

[вставить исходный отчёт]
```

Парсер ir-storyboard может использовать эту таблицу как вход для второго
прохода: `verdict=confirmed` → факт идёт в матрицу с обычным confidence;
`partial` → confidence × 0.7; `contradicted`/`not_found` → flag=grey,
needs_review=true; `dead_url` → попытаться Wayback и пометить.

---

## 6. Чеклист эксперта перед заливкой

Прежде чем нажать "Ingest" в ir-storyboard, эксперт проверяет:

- [ ] В отчёте есть все 9 секций по шаблону. Если LLM пропустил секцию — лучше
      попросить добор, чем ингестить дыру.
- [ ] В конце есть нумерованный список источников; каждый `[N]` в тексте
      имеет соответствующую запись.
- [ ] Раздел "Open Questions" не пустой — даже один вопрос про L1–L3 (детство,
      ценности) лучше пустоты: он станет interview-question для аналитика.
- [ ] Файл сохранён в `.docx` / `.md` / `.pdf`. Скриншоты и буфер обмена
      парсер не принимает.
- [ ] Если использовалась альтернативная LLM (не Deep Research) — эксперт
      указывает её при загрузке (для аудит-журнала).
