import { cn } from "@/lib/utils";

/** Match score as a ring. Colour follows the band so a 72 "review" never looks like a pass. */
export function ScoreRing({
  score,
  band,
  size = 44,
  className,
}: {
  score: number | null | undefined;
  band?: string | null;
  size?: number;
  className?: string;
}) {
  const stroke = 4;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const value = score === null || score === undefined ? null : Math.max(0, Math.min(100, score));
  const color =
    band === "high" ? "var(--success)" : band === "review" ? "var(--violet)" : "var(--text-3)";
  return (
    <div
      className={cn("relative grid shrink-0 place-items-center", className)}
      style={{ width: size, height: size }}
      aria-label={value === null ? "Not scored" : `Match score ${Math.round(value)} of 100`}
      role="img"
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--line-strong)" strokeWidth={stroke} />
        {value !== null ? (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - value / 100)}
            className="transition-[stroke-dashoffset] duration-700 ease-[var(--ease-orbit)]"
          />
        ) : null}
      </svg>
      <span className="absolute font-heading text-[13px] font-semibold text-text-1 tabular">
        {value === null ? "—" : Math.round(value)}
      </span>
    </div>
  );
}
