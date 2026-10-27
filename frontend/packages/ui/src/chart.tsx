export interface ChartSeries {
  name: string;
  color: string;
  data: Array<number | null>;
}

export interface LineChartProps {
  labels: string[];
  series: ChartSeries[];
  /** y 轴最大值（缺省时按数据取整放大），值为 0 时显示空说明 */
  yMax?: number;
  unit?: string;
  emptyHint?: string;
  height?: number;
}

const W = 420;
const PAD = { left: 34, right: 12, top: 12, bottom: 22 };

function niceMax(value: number): number {
  if (value <= 0) return 60;
  const step = value / 4;
  const magnitude = 10 ** Math.floor(Math.log10(step));
  const rounded = Math.ceil(step / magnitude) * magnitude;
  return rounded * 4 || 4;
}

export function LineChart({ labels, series, yMax: yMaxProp, unit = "", emptyHint }: LineChartProps) {
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

  const pointsFor = (line: ChartSeries) =>
    line.data.map((value, index) => {
      if (value == null) return null;
      const x = PAD.left + xStep * index;
      const y = PAD.top + innerHeight - (value / max) * innerHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

  const yTicks = [0, 1, 2, 3, 4].map((tick) => ({
    value: (max / 4) * tick,
    y: PAD.top + innerHeight - (innerHeight / 4) * tick,
  }));

  return (
    <div className="chart" role="img" aria-label={`折线图：${series.map((line) => line.name).join("、")}，纵轴 ${unit}`}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="none">
        {yTicks.map((tick, index) => (
          <g key={index}>
            <line x1={PAD.left} x2={W - PAD.right} y1={tick.y} y2={tick.y}
              stroke={index === 0 ? "var(--muted)" : "var(--line)"} strokeWidth="1" />
            <text x={PAD.left - 6} y={tick.y + 3} textAnchor="end" fontSize="9" fill="var(--muted)">
              {Math.round(tick.value)}{unit}
            </text>
          </g>
        ))}
        {labels.map((label, index) => (
          <text key={label} x={PAD.left + xStep * index} y={H - 6} textAnchor="middle" fontSize="9.5" fill="var(--muted)">
            {label}
          </text>
        ))}
        {dataLines.map((line) => {
          const points = pointsFor(line);
          const segments = points
            .map((point, index) => (point ? { point, index } : null))
            .filter((item): item is { point: string; index: number } => item != null);
          if (!segments.length) return null;
          return (
            <g key={line.name} opacity={hasData ? 1 : 0.25}>
              <polyline fill="none" stroke={line.color} strokeWidth="2" strokeLinejoin="round"
                strokeDasharray={hasData ? undefined : "3 5"}
                points={segments.map((item) => item.point).join(" ")} />
              {hasData ? segments.map(({ point, index }) => {
                const [x, y] = point.split(",");
                return (<circle key={index} cx={x} cy={y} r="2.4" fill={line.color} />);
              }) : null}
            </g>
          );
        })}
      </svg>
      {!hasData ? (
        <div className="chart-empty-hint" aria-live="polite">
          <strong>{emptyHint ?? "本周还没有学习记录"}</strong>
        </div>
      ) : null}
    </div>
  );
}

export function ChartLegend({ items }: { items: Array<{ name: string; color: string }> }) {
  return (
    <div className="legend">
      {items.map((item) => (
        <span key={item.name}><b style={{ background: item.color }} />{item.name}</span>
      ))}
    </div>
  );
}

export interface BarChartProps {
  labels: string[];
  data: Array<number | null>;
  color?: string;
  unit?: string;
  emptyHint?: string;
}

export function BarChart({ labels, data, color = "#d9a66b", unit = "", emptyHint }: BarChartProps) {
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

  return (
    <div className="chart" role="img" aria-label={`柱状图：${unit}`}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="none">
        {yTicks.map((tick, index) => (
          <g key={index}>
            <line x1={PAD.left} x2={W - PAD.right} y1={tick.y} y2={tick.y}
              stroke={index === 0 ? "var(--muted)" : "var(--line)"} strokeWidth="1" />
            <text x={PAD.left - 6} y={tick.y + 3} textAnchor="end" fontSize="9" fill="var(--muted)">
              {Math.round(tick.value)}{unit}
            </text>
          </g>
        ))}
        {labels.map((label, index) => {
          const value = data[index] ?? 0;
          const barHeight = Math.max(2, (value / max) * innerHeight);
          const x = PAD.left + slot * index + (slot - barWidth) / 2;
          const y = PAD.top + innerHeight - barHeight;
          return (
            <g key={label}>
              <rect x={x} y={y} width={barWidth} height={barHeight} fill={color} rx="2" />
              <text x={PAD.left + slot * index + slot / 2} y={H - 6} textAnchor="middle" fontSize="9.5" fill="var(--muted)">
                {label}
              </text>
            </g>
          );
        })}
      </svg>
      {!hasData ? (
        <div className="chart-empty-hint" aria-live="polite">
          <strong>{emptyHint ?? "暂无数据"}</strong>
        </div>
      ) : null}
    </div>
  );
}
