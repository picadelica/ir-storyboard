import type { Flag } from "../types";

interface FlagDotProps {
  flag: Flag | string;
  size?: number;
  className?: string;
}

export default function FlagDot({ flag, size = 8, className = "" }: FlagDotProps) {
  const bg =
    flag === "green" ? "bg-flag-green" :
    flag === "red"   ? "bg-flag-red"   :
                       "bg-flag-grey";
  return (
    <span
      className={`inline-block rounded-full shrink-0 ${bg} ${className}`}
      style={{ width: size, height: size }}
      aria-label={`${flag} flag`}
      title={`${flag} flag`}
    />
  );
}
