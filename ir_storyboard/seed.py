"""Seed data for the Accumulator pilot — extracted from DE.pdf (the 8-layer
framework example).

Each batch is fed through the methodologically correct channel:
  - founder personal layer → online_interview / offline_interview
  - founder professional → archival / online_research
  - community professional → archival / online_research
  - product, social impact, PEST → online_research / archival
This lets the prototype demonstrate how the channel-routing constraint works.
"""
from __future__ import annotations

import sqlite3
from typing import List

from . import matrix
from .channels import (
    OnlineResearchChannel, OnlineInterviewChannel,
    ArchivalChannel, OfflineInterviewChannel,
)
from .channels.base import IngestPayload, PreFact


CLIENT_ID = "accumulator"
CLIENT_NAME = "Accumulator"
SECTOR = "fintech / private equity infrastructure"
ONE_LINER = ("Equity pooling for unicorn founders — turn paper-billion stakes "
             "into a diversified, liquid pool, regulated under SEC.")


def _pf(text: str, sid: str, flag: str = "green", rationale: str = "") -> PreFact:
    return PreFact(text=text, subsection_id=sid, flag=flag, rationale=rationale)


def load_accumulator(conn: sqlite3.Connection) -> None:
    matrix.upsert_client(conn, CLIENT_ID, CLIENT_NAME, sector=SECTOR, one_liner=ONE_LINER)
    matrix.ensure_full_grid(conn, CLIENT_ID)

    # ---------------- Online interview channel: layers 1, 2 ----------------
    online_iv = OnlineInterviewChannel()
    online_iv.ingest(conn, IngestPayload(
        client_id=CLIENT_ID,
        source_title="Founder podcasts & public talks (composite)",
        source_url="",
        notes="Synthetic ingest of multiple public interviews. In production, "
              "feed real transcripts here.",
        raw_text="",
        pre_facts=[
            _pf("Дэйв Вайзер — серийный предприниматель, более 20 лет в Кремниевой долине и Израиле; "
                "построил 6 компаний, привлёк >$1 млрд", "2.1"),
            _pf("Оскар Хартманн родился 14 мая 1982 года в Казахстане (г. Джамбул)", "1.1"),
            _pf("Хартманн начал работать в 11 лет — газеты, склады, заправки", "1.1"),
            _pf("Происхождение и детство Дэйва Вайзера в публичных интервью не раскрыты "
                "(только упоминание о 20-летнем стаже)", "1.1", flag="grey"),
            _pf("Происхождение и ранние годы Максима Темчука в публичных источниках отсутствуют", "1.1", flag="grey"),
            _pf("Вайзер верит: его миссия — объединить величайших деятелей нашего времени", "1.2"),
            _pf("Хартманн: семья и жена Татьяна спасли его от превращения в 'бизнес-машину'", "1.2"),
            _pf("Вайзер пережил отмену IPO Gett из-за войны — $170 млн 'бумажного' состояния "
                "обнулились в одну ночь", "1.3"),
            _pf("Хартманн открыто признаёт 'ошибку на $300 миллионов' при инвестиции в Ozon — "
                "превращает её в опыт, а не травму", "1.3"),
            _pf("Вайзер мечтает создать Founders OS — операционную систему для предпринимателей: "
                "ликвидность, фандрайзинг, здоровье", "1.3"),
            _pf("Цель — объединить 12 000 основателей единорогов в глобальную сеть взаимной поддержки", "1.3"),
            _pf("Вайзер — 'Архитектор Ликвидности'; роль — строить Founders OS", "2.2"),
            _pf("Хартманн — 'Защитник Ангелов'; отвечает за Angels Fund II", "2.2"),
        ],
    ))

    # ---------------- Archival channel: layers 2, 3, 4 ----------------
    archival = ArchivalChannel()
    archival.ingest(conn, IngestPayload(
        client_id=CLIENT_ID,
        source_title="SEC filings + Founders Forum archives + press archive",
        source_url="",
        raw_text="",
        pre_facts=[
            _pf("Под руководством Вайзера Gett масштабирован до 1500 городов, обслуживая Fortune 500", "2.1"),
            _pf("Хартманн основал 10 компаний (KupiVIP, CarPrice, Aktivo); инвестировал в 100+ проектов", "2.1"),
            _pf("Вайзер фокусируется на Founders Fund I; Хартманн — на Angels Fund II — "
                "функциональная синергия, не конкуренция", "2.3"),
            _pf("Распределение долей между Вайзером, Хартманном и Темчуком — нет данных в источниках", "2.3", flag="grey"),
            _pf("Описание того, как сооснователи принимают решения в моменты разногласий — нет данных", "2.3", flag="grey"),
            _pf("Сообщество invite-only: оценка компании >$100 млн, раунд в 2024+, runway >18 месяцев", "3.1"),
            _pf("Тех, кто не дотягивает до критериев, отправляют в 'лист ожидания'", "3.1"),
            _pf("Founders Angels Forum в Лондоне — закрытое мероприятие для топ-ангелов", "3.2"),
            _pf("Unicorn Circle — внутренний 'энергоцентр' экспертизы", "3.2"),
            _pf("Внутренние ритуалы и общие чаты — нет данных в источниках", "3.2", flag="grey"),
            _pf("$46 млн инвестиций привлечено исключительно от самих участников сообщества", "3.3"),
            _pf("Среди инвесторов: Авишай Абраами (Wix), Филип Дамес (Zalando), Джиджи Леви-Вайсс (NFX), "
                "Фабрис Гринда (FJ Labs)", "3.3"),
            _pf("Стратегический альянс с Founders Forum Group Брента Хобермана — 'Давос для технологов'", "3.3"),
            _pf("В пуле — лидеры разных индустрий: SpaceX, Discord, Perplexity, Vercel, Monzo, N26, Qonto", "4.1"),
            _pf("География — Майами, Тель-Авив, Лондон, Нью-Йорк, Москва", "4.1"),
            _pf("Запущены 3 фонда: Founders Fund I, Angels Fund II, Index Fund III; AUM >$60 млн", "4.2"),
            _pf("Хартманн открыто включает в 'актив' свои промахи: $300 млн в Ozon; "
                "Fab.com обесценилась с $1.5 млрд до нуля за полгода", "4.3"),
            _pf("В портфеле есть и закрытые проекты (Vigoda, deadpooled) — даёт глубокое понимание рисков", "4.3"),
        ],
    ))

    # ---------------- Online research channel: layers 5, 6, 7, 8 ----------------
    online_research = OnlineResearchChannel()
    online_research.ingest(conn, IngestPayload(
        client_id=CLIENT_ID,
        source_title="Sector news, sell-side notes, market reports",
        source_url="",
        raw_text="",
        pre_facts=[
            _pf("'Бумажные миллионеры': основатель владеет 60–80% компании на $100 млн при скромной зарплате", "5.1"),
            _pf("Ловушка концентрации — почти весь net worth в одном неликвидном активе", "5.1"),
            _pf("Equity pooling: обмен акций без дисконта по оценке последнего раунда", "5.2"),
            _pf("Альтернатива — secondary с дисконтом 10–20% и высокими налогами", "5.2"),
            # 5.3 — leave intentionally weak: only an explicit grey note, no green coverage.
            # Demonstrates "we know we don't know — needs offline interview to fill".
            _pf("Конкретные именные кейсы фаундеров с внутренними диалогами в момент подписания — "
                "нет в публичных источниках; нужны интервью с действующими участниками пула", "5.3", flag="grey"),
            _pf("Equity Pooling: основной механизм — обмен части акций на долю в "
                "диверсифицированном пуле топовых компаний", "6.1"),
            _pf("Регулируется SEC США как фонд акций (Rule 506(b), Section 3(c)(1))", "6.1"),
            _pf("Философия 'Equity in motion' — превратить статичное бумажное богатство в живой актив", "6.2"),
            _pf("Сообщество как ценность: 'фаундеры инвестируют в фаундеров'", "6.2"),
            _pf("От stealth-режима к оценке $140 млн (декабрь 2024); расширение от Founders Fund I "
                "к Angels Fund II и Index Fund III", "6.3"),
            _pf("Конкретный график следующих milestone и unit economics (Mgmt Fee, Carry) "
                "не раскрыт публично", "6.3", flag="grey"),
            _pf("Видение: финансовые 'рельсы' для частного техсектора объёмом $6 трлн", "7.1"),
            _pf("Founders OS — экосистема (Accumulator + Fundraisly + KamaLama)", "7.1"),
            _pf("Цена сложности: exchange funds заметно сложнее обычных secondaries — "
                "требуют доверия к управляющему и юридической грамотности", "7.2", flag="red",
                rationale="Сложность продукта повышает порог входа и требует "
                          "повышенного due diligence у инвестора и фаундера."),
            _pf("Защита 'крови инноваций' — фаундеров и ангелов от 'смерти на бумаге'", "7.3"),
            _pf("С 1996 года число публичных компаний в США сократилось почти вдвое (с >7000 до <4000)", "8.1"),
            _pf("Stay Private Longer: средний возраст выхода на IPO вырос до 9–11 лет", "8.1"),
            _pf("Отмена IPO Gett из-за войны как личный катализатор и одновременно — "
                "архетипический пример системного риска", "8.1"),
            _pf("Частный техсектор: $6 трлн заблокированных активов; AUM private equity вырос "
                "с 2% до 7% от global AUM за 20 лет", "8.2"),
            _pf("Вторичный рынок достиг $110 млрд только в H1 2025", "8.2"),
            _pf("Геополитическая напряжённость, тарифная инфляция и волатильность ставок "
                "усложняют underwriting активов", "8.2", flag="red",
                rationale="Макро-волатильность напрямую снижает достоверность "
                          "оценок частных активов в пуле."),
            _pf("Использование Rule 506(b) и Section 3(c)(1) обеспечивает юридическую чистоту "
                "обмена акций; JOBS Act 2012 поднял лимит акционеров до 2000", "8.3"),
            _pf("В ЕС трансграничные операции фондов остаются дорогими и сложными "
                "из-за фрагментированного регулирования", "8.3", flag="red",
                rationale="Регуляторная фрагментация ЕС ограничивает географическое "
                          "масштабирование equity pooling за пределы США."),
        ],
    ))

    # ---------------- Offline interview channel: deliberately leave gaps ----------------
    # In a real deployment this is where the analyst's own interviews land.
    # For the demo, leave several inner-layer cells grey so the punch-list /
    # interview-questions output has something to recommend.
    offline_iv = OfflineInterviewChannel()
    offline_iv.ingest(conn, IngestPayload(
        client_id=CLIENT_ID,
        source_title="(no offline interviews recorded yet)",
        source_url="",
        raw_text="",
        pre_facts=[],   # intentionally empty
    ))

    # ---------------- Plan + narrative tracks for 2026Q2 ----------------
    plan_id = matrix.upsert_plan(conn, CLIENT_ID, "2026Q2",
        notes="Pilot quarter — focus on liquidity narrative + community story.")
    matrix.add_track(conn,
        plan_id=plan_id,
        name="Liquidity rails for $6T private market",
        angle="Stay-private-longer + secondary boom = window for equity pooling.",
        target_layer_ids=[5, 6, 7, 8],
        target_subsection_ids=["5.1", "5.2", "6.1", "7.1", "8.1", "8.2"],
        priority=3,
    )
    matrix.add_track(conn,
        plan_id=plan_id,
        name="Founders OS — beyond liquidity",
        angle="Wider ecosystem: fundraising (Fundraisly) and energy (KamaLama).",
        target_layer_ids=[1, 2, 7],
        target_subsection_ids=["1.3", "2.2", "7.1", "7.3"],
        priority=2,
    )
    matrix.add_track(conn,
        plan_id=plan_id,
        name="Unicorn solidarity",
        angle="Founders investing in founders — closed circle, mutual vested interest.",
        target_layer_ids=[3, 4],
        target_subsection_ids=["3.1", "3.2", "3.3", "4.1", "4.2"],
        priority=1,
    )
