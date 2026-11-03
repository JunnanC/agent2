import { jsx as _jsx } from "react/jsx-runtime";
import { useRef, useState } from "react";
export function Splitter({ orientation, ariaLabel, minSize, maxSize, currentSize, onChange, }) {
    const containerRef = useRef(null);
    const [dragging, setDragging] = useState(false);
    const startDrag = (event) => {
        event.preventDefault();
        containerRef.current = event.currentTarget.parentElement;
        setDragging(true);
        document.body.classList.add("layout-resizing", orientation === "vertical" ? "resize-columns" : "resize-rows");
        const move = (moveEvent) => {
            if (!containerRef.current)
                return;
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
    const onKeyDown = (event) => {
        const step = event.shiftKey ? 40 : 20;
        if (orientation === "vertical") {
            if (event.key === "ArrowLeft") {
                event.preventDefault();
                onChange(currentSize - step, true);
            }
            if (event.key === "ArrowRight") {
                event.preventDefault();
                onChange(currentSize + step, true);
            }
        }
        else {
            if (event.key === "ArrowUp") {
                event.preventDefault();
                onChange(currentSize + step, true);
            }
            if (event.key === "ArrowDown") {
                event.preventDefault();
                onChange(currentSize - step, true);
            }
        }
    };
    return (_jsx("div", { className: `workbench-splitter ${orientation === "vertical" ? "report-workbench-splitter" : "workspace-tests-splitter"}${dragging ? " is-dragging" : ""}`, role: "separator", "aria-label": ariaLabel, "aria-orientation": orientation === "vertical" ? "vertical" : "horizontal", "aria-valuemin": minSize, "aria-valuemax": maxSize, "aria-valuenow": Math.round(currentSize), tabIndex: 0, onPointerDown: startDrag, onKeyDown: onKeyDown }));
}
