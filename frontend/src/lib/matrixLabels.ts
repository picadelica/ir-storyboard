const LAYER_NAMES_RU: Record<number, string> = {
  1: "Личная история основателя",
  2: "Профессиональная история",
  3: "Культура и истории сообщества",
  4: "Профессиональный опыт сообщества",
  5: "Истории клиентов",
  6: "Продукт и бизнес",
  7: "Видение социального влияния",
  8: "Внешний контекст",
};

const LAYER_NAMES_BY_SOURCE: Record<string, string> = {
  "Founder Personal Story": LAYER_NAMES_RU[1],
  "Founder Professional Story": LAYER_NAMES_RU[2],
  "Community Culture, Values & Stories": LAYER_NAMES_RU[3],
  "Community Professional Experience": LAYER_NAMES_RU[4],
  "Clients - Stories": LAYER_NAMES_RU[5],
  "Product & Business": LAYER_NAMES_RU[6],
  "Social Impact Vision": LAYER_NAMES_RU[7],
  "Political, Economical, Social Context": LAYER_NAMES_RU[8],
};

const SUBSECTION_NAMES_RU: Record<string, string> = {
  "1.1": "Происхождение и детство",
  "1.2": "Ценности и убеждения",
  "1.3": "Страхи, мечты и идентичность",
  "2.1": "Путь к экспертизе",
  "2.2": "Отношения внутри команды",
  "2.3": "Отношения с инвесторами",
  "3.1": "Привлечение и отбор",
  "3.2": "Совместная жизнь",
  "3.3": "Инвесторы и партнёры",
  "4.1": "Экспертиза и разнообразие",
  "4.2": "Рост и трансформация",
  "4.3": "Память о неудачах",
  "5.1": "Задача и контекст клиента",
  "5.2": "Момент выбора и доверия",
  "5.3": "Конфликт и честность",
  "6.1": "Архитектура и философия",
  "6.2": "Рыночный контекст",
  "6.3": "Эволюция продукта",
  "7.1": "Видение изменений",
  "7.2": "Противоречия и цена",
  "7.3": "Наследие",
  "8.1": "Социальный контекст",
  "8.2": "Технологический контекст",
  "8.3": "Политика и экономика",
};

const SUBSECTION_NAMES_BY_SOURCE: Record<string, string> = {
  "Origin & Childhood": SUBSECTION_NAMES_RU["1.1"],
  "Values & Beliefs": SUBSECTION_NAMES_RU["1.2"],
  "Fears, Dreams & Identity": SUBSECTION_NAMES_RU["1.3"],
  "Path to Expertise": SUBSECTION_NAMES_RU["2.1"],
  "Team Relationships": SUBSECTION_NAMES_RU["2.2"],
  "Investor Relationships": SUBSECTION_NAMES_RU["2.3"],
  "Attraction & Selection": SUBSECTION_NAMES_RU["3.1"],
  "Living Together": SUBSECTION_NAMES_RU["3.2"],
  "Investors & Partners": SUBSECTION_NAMES_RU["3.3"],
  "Expertise & Diversity": SUBSECTION_NAMES_RU["4.1"],
  "Growth & Transformation": SUBSECTION_NAMES_RU["4.2"],
  "Memory of Failures": SUBSECTION_NAMES_RU["4.3"],
  "Client Problem & Context": SUBSECTION_NAMES_RU["5.1"],
  "Moment of Choice & Trust": SUBSECTION_NAMES_RU["5.2"],
  "Conflict & Honesty": SUBSECTION_NAMES_RU["5.3"],
  "Architecture & Philosophy": SUBSECTION_NAMES_RU["6.1"],
  "Market Context": SUBSECTION_NAMES_RU["6.2"],
  "Product Evolution": SUBSECTION_NAMES_RU["6.3"],
  "Vision of Change": SUBSECTION_NAMES_RU["7.1"],
  "Contradictions & Price": SUBSECTION_NAMES_RU["7.2"],
  "Legacy": SUBSECTION_NAMES_RU["7.3"],
  "Social Context": SUBSECTION_NAMES_RU["8.1"],
  "Technological Context": SUBSECTION_NAMES_RU["8.2"],
  "Politics & Economics": SUBSECTION_NAMES_RU["8.3"],
};

export function layerNameRu(id?: number | string | null, fallback = ""): string {
  const n = typeof id === "string" ? Number(id) : id;
  if (n && LAYER_NAMES_RU[n]) return LAYER_NAMES_RU[n];
  return fallback ? LAYER_NAMES_BY_SOURCE[fallback] || fallback : "";
}

export function subsectionNameRu(id?: string | null, fallback = ""): string {
  if (id && SUBSECTION_NAMES_RU[id]) return SUBSECTION_NAMES_RU[id];
  return fallback ? SUBSECTION_NAMES_BY_SOURCE[fallback] || fallback : "";
}

export function keepShortRuWords(text: string): string {
  return text.replace(/(^|\s)([АаВвИиКкОоСсУу])\s+/g, "$1$2\u00A0");
}
