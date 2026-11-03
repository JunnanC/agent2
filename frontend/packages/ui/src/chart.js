import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const W = 420;
const PAD = { left: 34, right: 12, top: 12, bottom: 22 };
function niceMax(value) {
    if (value <= 0)
        return 60;
    const step = value / 4;
    const magnitude = 10 ** Math.floor(Math.log10(step));
    const rounded = Math.ceil(step / magnitude) * magnitude;
    return rounded * 4 || 4;
}
export function LineChart({ labels, series, yMax: yMaxProp, unit = "", emptyHint }) {
    const H = 180;
    const nonEmpty = series.filter((line) => line.data.some((value) => value != null && value > 0));
    const hasData = nonEmpty.length > 0;
    const innerWidth = W - PAD.left - PAD.right;
    const innerHeight = H - PAD.top - PAD.bottom;
    // 空数据时保留坐标轴空图（基线为 0），并叠加居中提示
    const max = hasData
        ? (yMaxProp ?? niceMax(Math.max(...nonEmpty.flatMap((line) => line.data.map((v) => v ?? 0)))))
        : (yMaxProp ?? 60);
    const dataLines = hasData ? nonEmpty : series;
    const xStep = labels.length > 1 ? innerWidth / (labels.length - 1) : 0;
    const pointsFor = (line) => line.data.map((value, index) => {
        if (value == null)
            return null;
        const x = PAD.left + xStep * index;
        const y = PAD.top + innerHeight - (value / max) * innerHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const yTicks = [0, 1, 2, 3, 4].map((tick) => ({
        value: (max / 4) * tick,
        y: PAD.top + innerHeight - (innerHeight / 4) * tick,
    }));
    return (_jsxs("div", { className: "chart", role: "img", "aria-label": `折线图：${series.map((line) => line.name).join("、")}，纵轴 ${unit}`, children: [_jsxs("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", preserveAspectRatio: "none", children: [yTicks.map((tick, index) => (_jsxs("g", { children: [_jsx("line", { x1: PAD.left, x2: W - PAD.right, y1: tick.y, y2: tick.y, stroke: index === 0 ? "var(--muted)" : "var(--line)", strokeWidth: "1" }), _jsxs("text", { x: PAD.left - 6, y: tick.y + 3, textAnchor: "end", fontSize: "9", fill: "var(--muted)", children: [Math.round(tick.value), unit] })] }, index))), labels.map((label, index) => (_jsx("text", { x: PAD.left + xStep * index, y: H - 6, textAnchor: "middle", fontSize: "9.5", fill: "var(--muted)", children: label }, label))), dataLines.map((line) => {
                        const points = pointsFor(line);
                        const segments = points
                            .map((point, index) => (point ? { point, index } : null))
                            .filter((item) => item != null);
                        if (!segments.length)
                            return null;
                        return (_jsxs("g", { opacity: hasData ? 1 : 0.25, children: [_jsx("polyline", { fill: "none", stroke: line.color, strokeWidth: "2", strokeLinejoin: "round", strokeDasharray: hasData ? undefined : "3 5", points: segments.map((item) => item.point).join(" ") }), hasData ? segments.map(({ point, index }) => {
                                    const [x, y] = point.split(",");
                                    return (_jsx("circle", { cx: x, cy: y, r: "2.4", fill: line.color }, index));
                                }) : null] }, line.name));
                    })] }), !hasData ? (_jsx("div", { className: "chart-empty-hint", "aria-live": "polite", children: _jsx("strong", { children: emptyHint ?? "本周还没有学习记录" }) })) : null] }));
}
export function ChartLegend({ items }) {
    return (_jsx("div", { className: "legend", children: items.map((item) => (_jsxs("span", { children: [_jsx("b", { style: { background: item.color } }), item.name] }, item.name))) }));
}
export function BarChart({ labels, data, color = "#d9a66b", unit = "", emptyHint }) {
    const H = 180;
    const hasData = data.some((value) => value != null && value > 0);
    const max = niceMax(Math.max(...data.map((value) => value ?? 0)));
    const innerWidth = W - PAD.left - PAD.right;
    const innerHeight = H - PAD.top - PAD.bottom;
    const slot = innerWidth / Math.max(1, labels.length);
    const barWidth = Math.min(34, slot * 0.55);
    const yTicks = [0, 1, 2, 3, 4].map((tick) => ({
        value: (max / 4) * tick,
        y: PAD.top + innerHeight - (innerHeight / 4) * tick,
    }));
    return (_jsxs("div", { className: "chart", role: "img", "aria-label": `柱状图：${unit}`, children: [_jsxs("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", preserveAspectRatio: "none", children: [yTicks.map((tick, index) => (_jsxs("g", { children: [_jsx("line", { x1: PAD.left, x2: W - PAD.right, y1: tick.y, y2: tick.y, stroke: index === 0 ? "var(--muted)" : "var(--line)", strokeWidth: "1" }), _jsxs("text", { x: PAD.left - 6, y: tick.y + 3, textAnchor: "end", fontSize: "9", fill: "var(--muted)", children: [Math.round(tick.value), unit] })] }, index))), labels.map((label, index) => {
                        const value = data[index] ?? 0;
                        const barHeight = Math.max(2, (value / max) * innerHeight);
                        const x = PAD.left + slot * index + (slot - barWidth) / 2;
                        const y = PAD.top + innerHeight - barHeight;
                        return (_jsxs("g", { children: [_jsx("rect", { x: x, y: y, width: barWidth, height: barHeight, fill: color, rx: "2" }), _jsx("text", { x: PAD.left + slot * index + slot / 2, y: H - 6, textAnchor: "middle", fontSize: "9.5", fill: "var(--muted)", children: label })] }, label));
                    })] }), !hasData ? (_jsx("div", { className: "chart-empty-hint", "aria-live": "polite", children: _jsx("strong", { children: emptyHint ?? "暂无数据" }) })) : null] }));
}
