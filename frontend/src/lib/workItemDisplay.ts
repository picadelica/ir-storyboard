export function displayWorkTitle(title: string) {
  if (title.startsWith("Interview:")) return "Вопрос для интервью";
  if (title.startsWith("Fill gap:")) return "Добрать материал";
  if (title.startsWith("Deepen:")) return "Добрать подтверждения";
  if (title.startsWith("Verify: low-confidence fact")) return "Проверить слабый факт";
  return title;
}

export function displayWorkBody(title: string, body: string) {
  if (title.startsWith("Verify: low-confidence fact")) {
    const confidence = body.match(/confidence=([0-9.]+)/)?.[1];
    return confidence
      ? `Уверенность ${confidence} — нужно перепроверить источник или найти подтверждение.`
      : "Низкая уверенность — нужно перепроверить источник или найти подтверждение.";
  }
  if (title.startsWith("Fill gap:")) return "Нужно добрать материал, чтобы закрыть пустую или слабую позицию.";
  if (title.startsWith("Deepen:")) return "Фактов недостаточно: стоит добрать источники или подтверждения.";
  return body;
}

export function isFirstMaterialWorkTitle(title: string) {
  return title.startsWith("Interview:") || title.startsWith("Fill gap:");
}

export function isInterviewWorkTitle(title: string) {
  return title.startsWith("Interview:");
}
