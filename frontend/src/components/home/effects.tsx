import { cn } from "@/lib/utils";

/** Deterministic pseudo-random numbers, so the server and the browser place the same stars. */
function seeded(seed: number) {
  let value = seed;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

const STARS = (() => {
  const next = seeded(42);
  return Array.from({ length: 70 }, () => ({
    left: next() * 100,
    top: next() * 100,
    size: next() < 0.15 ? 2.5 : next() < 0.5 ? 1.5 : 1,
    delay: next() * 5,
    duration: 2.5 + next() * 3.5,
    cyan: next() < 0.25,
  }));
})();

/** Twinkling stars, dark theme only: on a light page they would read as dust. */
export function Starfield({
  className,
  count = STARS.length,
}: {
  className?: string;
  count?: number;
}) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 hidden overflow-hidden dark:block",
        className,
      )}
    >
      {STARS.slice(0, count).map((star, index) => (
        <span
          key={index}
          className={cn(
            "absolute rounded-full motion-reduce:animate-none",
            star.cyan
              ? "bg-cyan shadow-[0_0_6px_var(--cyan)]"
              : "bg-white shadow-[0_0_6px_white]",
          )}
          style={{
            left: `${star.left}%`,
            top: `${star.top}%`,
            width: star.size,
            height: star.size,
            opacity: 0.4,
            animation: `twinkle ${star.duration}s ease-in-out ${star.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

/** Two soft colour fields drifting slowly; stronger in the dark theme. */
export function Aurora({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className,
      )}
    >
      <div
        className="absolute -left-[10%] -top-[20%] h-[70%] w-[60%] rounded-full blur-3xl motion-reduce:animate-none dark:mix-blend-screen"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklch, var(--violet) 32%, transparent), transparent)",
          opacity: "var(--fx-aurora)",
          animation: "aurora-drift 18s ease-in-out infinite",
        }}
      />
      <div
        className="absolute -right-[10%] top-[5%] h-[60%] w-[50%] rounded-full blur-3xl motion-reduce:animate-none dark:mix-blend-screen"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklch, var(--cyan) 24%, transparent), transparent)",
          opacity: "var(--fx-aurora)",
          animation: "aurora-drift 24s ease-in-out -8s infinite reverse",
        }}
      />
    </div>
  );
}
