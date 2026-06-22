import type { Flag } from "../types";

interface FlagDotProps {
  flag: Flag | string;
  mustHave?: boolean;   // client-provided must-have → blue, overrides the flag colour
  size?: number;
  className?: string;
}

export default function FlagDot({ flag, mustHave = false, size = 8, className = "" }: FlagDotProps) {
  const bg =
    mustHave         ? "bg-flag-blue"  :
    flag === "green" ? "bg-flag-green" :
    flag === "red"   ? "bg-flag-red"   :
                       "bg-flag-grey";
  const label = mustHave ? "must-have (от клиента)" : `${flag} flag`;
  return (
    <span
      className={`inline-block rounded-full shrink-0 ${bg} ${className}`}
      style={{ width: size, height: size }}
      aria-label={label}
      title={label}
    />
  );
}
