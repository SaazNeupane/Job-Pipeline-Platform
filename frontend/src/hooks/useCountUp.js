import { useEffect, useState } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// Animates a stat number counting up from 0 to `value` once, on mount/value change --
// ease-out over `duration`ms. Skips straight to `value` if the OS/browser has reduced
// motion set, since this is a JS rAF loop rather than a CSS transition and doesn't fall
// under index.css's global prefers-reduced-motion override.
export function useCountUp(value, duration = 500) {
  const [display, setDisplay] = useState(prefersReducedMotion() ? value : 0);

  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(value)) {
      setDisplay(value);
      return;
    }
    let frame;
    const start = performance.now();
    const from = 0;
    function tick(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(from + (value - from) * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return display;
}
