import { useEffect, useRef } from "react";

const CONFIG = {
  size: 12,
  easing: 0.18,
  idleOpacity: 0.36,
  activeOpacity: 0.78,
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function DragonCompanionOverlay() {
  const dotRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const finePointer = window.matchMedia("(pointer: fine)");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!finePointer.matches || reducedMotion.matches) {
      return;
    }

    const dot = dotRef.current;
    if (!dot) return;

    let rafId = 0;
    let disposed = false;
    let lastMoveAt = performance.now();

    const pointer = {
      x: window.innerWidth * 0.5,
      y: window.innerHeight * 0.4,
      active: false,
    };

    const follower = {
      x: pointer.x,
      y: pointer.y,
    };

    const step = (time: number) => {
      if (disposed) return;

      follower.x += (pointer.x - follower.x) * CONFIG.easing;
      follower.y += (pointer.y - follower.y) * CONFIG.easing;

      const idleAmount = clamp((time - lastMoveAt) / 900, 0, 1);
      const opacity =
        CONFIG.activeOpacity - (CONFIG.activeOpacity - CONFIG.idleOpacity) * idleAmount;
      const scale = 1 - idleAmount * 0.08;

      dot.style.transform = `translate3d(${follower.x - CONFIG.size / 2}px, ${follower.y - CONFIG.size / 2}px, 0) scale(${scale})`;
      dot.style.opacity = `${opacity}`;

      rafId = window.requestAnimationFrame(step);
    };

    const handlePointerMove = (event: PointerEvent) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;
      lastMoveAt = performance.now();
    };

    const handlePointerLeave = () => {
      pointer.active = false;
      lastMoveAt = performance.now() - 900;
    };

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", handlePointerLeave);
    rafId = window.requestAnimationFrame(step);

    return () => {
      disposed = true;
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
    };
  }, []);

  return (
    <div className="dragon-overlay" aria-hidden="true">
      <div ref={dotRef} className="dragon-overlay__dot" />
    </div>
  );
}
