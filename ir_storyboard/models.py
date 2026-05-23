"""Domain dataclasses + the canonical 8-layer schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# ---------- canonical layers (concentric, intimacy 1=innermost ... 8=outermost) ----------

# Channel codes — keep in sync with schema.sql CHECK constraint
CHANNEL_ONLINE_RESEARCH = "online_research"
CHANNEL_ONLINE_INTERVIEW = "online_interview"
CHANNEL_ARCHIVAL = "archival"
CHANNEL_OFFLINE_INTERVIEW = "offline_interview"

ALL_CHANNELS = (
    CHANNEL_ONLINE_RESEARCH,
    CHANNEL_ONLINE_INTERVIEW,
    CHANNEL_ARCHIVAL,
    CHANNEL_OFFLINE_INTERVIEW,
)

FLAG_GREEN = "green"
FLAG_RED = "red"
FLAG_GREY = "grey"

CYCLE_WEEKLY = "weekly"
CYCLE_EVENT = "event"
CYCLE_QUARTERLY = "quarterly"


@dataclass
class LayerSpec:
    id: int
    code: str
    name: str
    intimacy: int                 # 1=innermost, 8=outermost
    primary_channels: List[str]   # which channels can feed this layer
    subsections: List["SubsectionSpec"] = field(default_factory=list)


@dataclass
class SubsectionSpec:
    id: str          # '1.1'
    code: str        # 'ORIGIN_CHILDHOOD'
    name: str        # 'Origin & Childhood'
    description: str = ""
    sort_order: int = 0


@dataclass
class Fact:
    id: Optional[int]
    cell_id: int
    text: str
    flag: str             # green / red / grey
    source_id: Optional[int]
    confidence: float = 1.0


@dataclass
class Source:
    id: Optional[int]
    channel: str
    title: str = ""
    url: str = ""
    notes: str = ""


@dataclass
class NarrativeTrack:
    id: Optional[int]
    plan_id: int
    name: str
    angle: str
    target_layer_ids: List[int]
    target_subsection_ids: List[str]
    priority: int = 1


# ---------- the canonical 8 layers (matches the framework PDF) ----------

LAYERS: List[LayerSpec] = [
    LayerSpec(
        id=1, code="FOUNDER_PERSONAL", name="Founder Personal Story",
        intimacy=1,
        # personal layer is built almost entirely from interviews
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW],
        subsections=[
            SubsectionSpec("1.1", "ORIGIN_CHILDHOOD", "Origin & Childhood",
                           description=(
                               "Раннее детство и семейный фон фаундера: где и в какой среде родился, "
                               "состав семьи, отношения с родителями, школа, формирующие события до 18 лет. "
                               "Сюда — конкретные сцены и факты биографии. НЕ сюда: профессиональные "
                               "достижения (это L2), убеждения (L1.2) или внутренние страхи (L1.3)."
                           ),
                           sort_order=1),
            SubsectionSpec("1.2", "VALUES_BELIEFS", "Values & Beliefs",
                           description=(
                               "Декларируемые ценности и убеждения фаундера: что он считает важным, "
                               "правильным, неправильным; этические ориентиры, мировоззренческие позиции. "
                               "Сюда — прямые высказывания о ценностях и принципах. НЕ сюда: страхи "
                               "(L1.3), а также бизнес-философия продукта (L6.2)."
                           ),
                           sort_order=2),
            SubsectionSpec("1.3", "FEARS_DREAMS_IDENTITY", "Fears, Dreams & Identity",
                           description=(
                               "Внутренний мир: страхи, уязвимости, мечты, самоидентичность, кризисы "
                               "и моменты сомнений. Сюда — личные откровения о страхах и идентичности. "
                               "НЕ сюда: рациональные ценности (L1.2), профессиональная мотивация (L2.2)."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=2, code="FOUNDER_PROFESSIONAL", name="Founder Professional Story",
        intimacy=2,
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("2.1", "PATH_TO_EXPERTISE", "Path to expertise",
                           description=(
                               "Образование, ключевые работы, проекты до текущего стартапа — как "
                               "формировалась экспертиза. Сюда — конкретные позиции, компании, годы, "
                               "степени, профильные исследования. НЕ сюда: личная мотивация фаундерства "
                               "(L2.2), команда (L4)."
                           ),
                           sort_order=1),
            SubsectionSpec("2.2", "FOUNDER_ROLE_MOTIVATION", "Founder role & motivation",
                           description=(
                               "Почему фаундер пошёл в фаундерство этой конкретной компании: триггер, "
                               "роль в команде (CEO/CTO/etc), что движет именно в этом проекте. Сюда — "
                               "обоснование выбора задачи и роли. НЕ сюда: общий карьерный путь (L2.1)."
                           ),
                           sort_order=2),
            SubsectionSpec("2.3", "COFOUNDER_DYNAMICS", "Co-founder dynamics",
                           description=(
                               "Отношения и динамика с со-фаундерами: как познакомились, разделение "
                               "ролей и зон ответственности, конфликты и их разрешение. Сюда — "
                               "конкретика про со-фаундеров. НЕ сюда: вся команда в целом (L4)."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=3, code="COMMUNITY_CULTURE", name="Community Culture, Values & Stories",
        intimacy=3,
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("3.1", "ATTRACTION_SELECTION", "Attraction & Selection",
                           description=(
                               "Как формируется сообщество вокруг компании: критерии отбора людей, "
                               "приглашение в сообщество (advisors, ангелы, эксперты, фанаты), что "
                               "привлекает. Сюда — принципы и кейсы пополнения. НЕ сюда: сотрудники "
                               "(L4), клиенты (L5), инвесторы (L3.3 отдельно)."
                           ),
                           sort_order=1),
            SubsectionSpec("3.2", "SHARED_LIFE", "Shared life",
                           description=(
                               "Общие события, ритуалы, культура сообщества: что объединяет, какие "
                               "мероприятия, традиции, форумы, общая мифология. Сюда — конкретные "
                               "события и ритуалы. НЕ сюда: внутрифирменная культура команды (L4)."
                           ),
                           sort_order=2),
            SubsectionSpec("3.3", "INVESTORS_PARTNERS", "Investors & Partners",
                           description=(
                               "Структура инвесторов и стратегических партнёров: кто, когда вошёл, на "
                               "каких условиях, чем помогают помимо денег. Сюда — раунды, имена фондов "
                               "и партнёров, их роль. НЕ сюда: фаундер сам (L2), команда (L4)."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=4, code="COMMUNITY_PROFESSIONAL", name="Community Professional Experience",
        intimacy=4,
        primary_channels=[CHANNEL_ARCHIVAL, CHANNEL_ONLINE_RESEARCH, CHANNEL_ONLINE_INTERVIEW],
        subsections=[
            SubsectionSpec("4.1", "EXPERTISE_DIVERSITY", "Expertise & Diversity",
                           description=(
                               "Компетенции команды и её разнообразие: какие специалисты, откуда пришли, "
                               "как сбалансирован стек экспертиз. Сюда — состав команды, ключевые наймы, "
                               "diversity-факты. НЕ сюда: только фаундер (L2), процессы роста (L4.2)."
                           ),
                           sort_order=1),
            SubsectionSpec("4.2", "GROWTH_TRANSFORMATION", "Growth & Transformation",
                           description=(
                               "Как растёт и меняется команда: численность по этапам, организационные "
                               "изменения, переходы (стартап → scale-up), переезды офиса. Сюда — динамика "
                               "размера и структуры. НЕ сюда: состав на сейчас (L4.1)."
                           ),
                           sort_order=2),
            SubsectionSpec("4.3", "COLLECTIVE_FAILURE_MEMORY", "Collective Failure Memory",
                           description=(
                               "Коллективные провалы, ошибки, кризисы команды: что не получилось, кого "
                               "потеряли, какие выводы сделали как организация. Сюда — конкретные "
                               "incidents и их разбор. НЕ сюда: личные провалы фаундера (L1.3 / L2)."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=5, code="CLIENTS_STORIES", name="Clients - Stories",
        intimacy=5,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("5.1", "CLIENT_CHALLENGE_CONTEXT", "Client's challenge & context",
                           description=(
                               "Контекст и проблема клиента до контакта с компанией: какие боли, "
                               "ограничения, в каких условиях клиент работал. Сюда — описания клиентских "
                               "ситуаций. НЕ сюда: продукт компании (L6), решение проблемы (L5.2)."
                           ),
                           sort_order=1),
            SubsectionSpec("5.2", "MOMENT_OF_CHOICE_TRUST", "Moment of choice & trust",
                           description=(
                               "Момент выбора и формирования доверия: почему клиент выбрал именно эту "
                               "компанию, какие были альтернативы, что переломило в пользу выбора. Сюда — "
                               "решения о покупке и их обоснование. НЕ сюда: продукт сам (L6)."
                           ),
                           sort_order=2),
            SubsectionSpec("5.3", "CONFLICT_HONESTY", "Conflict & Honesty",
                           description=(
                               "Конфликты с клиентами, ошибки в работе, моменты честности (или её "
                               "отсутствия) — как компания признаёт и разрешает проблемы. Сюда — "
                               "конкретные истории напряжения и их исход."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=6, code="PRODUCT_BUSINESS", name="Product & Business",
        intimacy=6,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("6.1", "ARCHITECTURE_OF_SOLUTION", "Architecture of the solution",
                           description=(
                               "Устройство продукта/решения: технологический стек, ключевые компоненты, "
                               "как устроено under the hood, патенты, технические преимущества. Сюда — "
                               "конкретика про архитектуру и технологии."
                           ),
                           sort_order=1),
            SubsectionSpec("6.2", "PHILOSOPHY_PRODUCT_DECISIONS", "Philosophy of product decisions",
                           description=(
                               "Философия и принципы продуктовых решений: на чём основан дизайн, какие "
                               "trade-off'ы выбраны и почему, что компания принципиально НЕ делает. "
                               "Сюда — обоснование принципиальных решений. НЕ сюда: личные ценности (L1.2)."
                           ),
                           sort_order=2),
            SubsectionSpec("6.3", "EVOLUTION_OF_PRODUCT", "Evolution of the product",
                           description=(
                               "Как продукт эволюционировал: pivot'ы, ключевые версии и фичи, рост "
                               "продуктовой линейки. Сюда — таймлайн продуктовых изменений с датами."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=7, code="SOCIAL_IMPACT", name="Social Impact Vision",
        intimacy=7,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("7.1", "VISION_OF_CHANGE", "Vision of change",
                           description=(
                               "Декларируемая трансформация мира/индустрии, к которой компания идёт: "
                               "какие сдвиги она вызывает, кто бенефициары изменения. Сюда — "
                               "формулировки видения и его адресатов."
                           ),
                           sort_order=1),
            SubsectionSpec("7.2", "CONTRADICTIONS_COST", "Contradictions & Cost",
                           description=(
                               "Противоречия, компромиссы, цена изменения: кто проигрывает от "
                               "трансформации, какие trade-off'ы признаются, потенциальные "
                               "негативные последствия. Сюда — самокритика и trade-off'ы."
                           ),
                           sort_order=2),
            SubsectionSpec("7.3", "LEGACY", "Legacy",
                           description=(
                               "Долгосрочное наследие: что компания и фаундер хотят оставить после "
                               "себя, как видят влияние через 10-50 лет. Сюда — формулировки legacy "
                               "и долгосрочных целей."
                           ),
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=8, code="PEST_CONTEXT", name="Political, Economical, Social & Technological Context",
        intimacy=8,
        # outermost layer is best fed by online research
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("8.1", "HISTORICAL_MOMENT", "The historical moment",
                           description=(
                               "Исторический контекст: ключевые события и тренды эпохи, в которой "
                               "компания существует — войны, кризисы, культурные сдвиги. Сюда — "
                               "macro-события, влияющие на индустрию или сам стартап."
                           ),
                           sort_order=1),
            SubsectionSpec("8.2", "MARKET_TECHNOLOGY", "Market & technology",
                           description=(
                               "Состояние рынка и технологий: размер рынка, основные игроки, "
                               "технологические сдвиги (AI, биотех, климат и т.д.), конкурентная "
                               "среда. Сюда — внешние market/tech факты. НЕ сюда: продукт самой "
                               "компании (L6)."
                           ),
                           sort_order=2),
            SubsectionSpec("8.3", "POLICY_REGULATION", "Policy & regulation",
                           description=(
                               "Регулирование, политика, законы, влияющие на индустрию: "
                               "законопроекты, санкции, отраслевые ограничения, лоббирование. "
                               "Сюда — конкретные акты, регуляторы, политические решения."
                           ),
                           sort_order=3),
        ],
    ),
]


def layer_by_id(lid: int) -> LayerSpec:
    for L in LAYERS:
        if L.id == lid:
            return L
    raise KeyError(f"layer {lid} not found")


def subsection_by_id(sid: str) -> SubsectionSpec:
    for L in LAYERS:
        for s in L.subsections:
            if s.id == sid:
                return s
    raise KeyError(f"subsection {sid} not found")


def channel_can_fill(channel: str, layer_id: int) -> bool:
    """Methodological constraint: which channels can feed which layers."""
    return channel in layer_by_id(layer_id).primary_channels
