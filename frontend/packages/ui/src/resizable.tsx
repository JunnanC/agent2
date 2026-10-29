import { useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

export interface SplitterProps {
  /** vertical 为左右分栏（调整左栏宽度），horizontal 为上下分栏（调整下栏高度） */
  orientation: "vertical" | "horizontal";
  ariaLabel: string;
  minSize: number;
  maxSize: number;
  currentSize: number;
  onChange: (next: number, persist: boolean) => void;
}

export function Splitter({
  orientation, ariaLabel, minSize, maxSize, currentSize, onChange,
}: SplitterProps) {
  const containerRef = useRef<HTMLElement | null>(null);
  const [dragging, setDragging] = useState(false);

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    containerRef.current = event.currentTarget.parentElement as HTMLElement;
    setDragging(true);
    document.body.classList.add(
      "layout-resizing",
      orientation === "vertical" ? "resize-columns" : "resize-rows",
    );
    const move = (moveEvent: globalThis.PointerEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = orientation === "vertical"
        ? moveEvent.clientX - rect.left
        : rect.bottom - moveEvent.clientY;
      onChange(next, true);
    };
    const stop = () => {
      setDragging(false);
      document.body.classList.remove("layout-resizing", "resize-columns", "resize-rows");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 40 : 20;
    if (orientation === "vertical") {
      if (event.key === "ArrowLeft") { event.preventDefault(); onChange(currentSize - step, true); }
      if (event.key === "ArrowRight") { event.preventDefault(); onChange(currentSize + step, true); }
    } else {
      if (event.key === "ArrowUp") { event.preventDefault(); onChange(currentSize + step, true); }
      if (event.key === "ArrowDown") { event.preventDefault(); onChange(currentSize - step, true); }
    }
  };

  return (
    <div
      className={`workbench-splitter ${orientation === "vertical" ? "report-workbench-splitter" : "workspace-tests-splitter"}${dragging ? " is-dragging" : ""}`}
      role="separator"
      aria-label={ariaLabel}
      aria-orientation={orientation === "vertical" ? "vertical" : "horizontal"}
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      aria-valuenow={Math.round(currentSize)}
      tabIndex={0}
      onPointerDown={startDrag}
      onKeyDown={onKeyDown}
    />
  );
}
