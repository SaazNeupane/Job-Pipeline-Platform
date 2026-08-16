import { useEffect, useState } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// Types `text` out character by character on mount, calling `onDone` once the last
// character lands -- used to sequence the landing hero's prompt line, headline, and lede
// as one orchestrated moment instead of three separate unrelated animations. Renders the
// full text immediately (no typing) under prefers-reduced-motion.
export function useTypewriter(text, speed = 32, onDone) {
  const [shown, setShown] = useState(prefersReducedMotion() ? text : "");
  const [done, setDone] = useState(prefersReducedMotion());

  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(text);
      setDone(true);
      onDone?.();
      return;
    }
    let i = 0;
    setShown("");
    setDone(false);
    const id = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(id);
        setDone(true);
        onDone?.();
      }
    }, speed);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, speed]);

  return { shown, done };
}
