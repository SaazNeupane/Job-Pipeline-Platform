import { useEffect, useRef, useState } from "react";

// Returns a ref to attach to an element and a boolean that flips true once, the first
// time that element scrolls into the viewport -- drives the landing page's scroll-reveal
// on the process strip and guide steps. Stays true after the first reveal (no re-hiding
// on scroll back up, which would just be distracting on a second pass down the page).
export function useInViewport(threshold = 0.2) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [inView, threshold]);

  return [ref, inView];
}
