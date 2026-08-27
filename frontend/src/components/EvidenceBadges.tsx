type Props = {
  mustClient?: number;
  mustExpert?: number;
  corroborated?: boolean;
  compact?: boolean;
  className?: string;
};

export default function EvidenceBadges({
  mustClient = 0,
  mustExpert = 0,
  corroborated = false,
  compact = false,
  className = "",
}: Props) {
  const must = mustClient + mustExpert;
  if (!must && !corroborated) return null;
  const starColor = mustExpert > 0 && mustClient === 0 ? "text-[#756082]" : "text-[#5f789c]";
  const size = compact ? "text-[9px]" : "text-[10px]";
  const gap = compact ? "gap-0.5" : "gap-1";
  const itemGap = compact ? "gap-[3px]" : "gap-1";
  const iconBox = compact ? "w-[7px]" : "w-2";
  return (
    <span className={`inline-flex items-center ${gap} ${size} font-medium leading-none tabular-nums ${className}`}>
      {must > 0 && (
        <span
          className={`inline-grid grid-cols-[auto_auto] items-center ${itemGap} ${starColor}`}
          title={[
            mustClient ? `${mustClient} обязательных от клиента` : "",
            mustExpert ? `${mustExpert} важных от эксперта` : "",
          ].filter(Boolean).join(" · ") || "must-have"}
        >
          <span className={`${iconBox} inline-flex justify-center leading-none text-[0.78em]`}>★</span>
          <span>{must}</span>
        </span>
      )}
      {must > 0 && corroborated && <span className="font-normal text-[#9a9d94]">·</span>}
      {corroborated && (
        <span className="inline-flex items-center text-[#7f8379]" title="Есть факты, подтвержденные 2+ источниками">
          <span className={`${iconBox} inline-flex justify-center leading-none text-[1.04em]`}>◆</span>
        </span>
      )}
    </span>
  );
}
