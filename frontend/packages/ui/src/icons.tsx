import type { CSSProperties, ReactNode } from "react";

export type IconName =
  | "layers" | "bell" | "chevron-down" | "chevron-left" | "chevron-right" | "chevron-up"
  | "x" | "menu" | "check" | "search" | "plus" | "arrow-right" | "arrow-left"
  | "user" | "users" | "calendar" | "calendar-clock" | "calendar-days" | "clock"
  | "flask" | "book" | "file-check" | "file-text" | "chart" | "trending-up"
  | "circle-check" | "circle-dashed" | "help" | "info" | "alert-triangle"
  | "play" | "send" | "bookmark-plus" | "paperclip" | "list" | "h3" | "lightbulb"
  | "log-out" | "copy" | "download" | "boxes" | "box" | "cpu" | "server" | "monitor"
  | "activity" | "gauge" | "refresh" | "shield" | "timer" | "message" | "settings" | "external";

const paths: Record<IconName, ReactNode> = {
  layers: (<><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /><path d="m3 18 9 5 9-5" /></>),
  bell: (<><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></>),
  "chevron-down": <path d="m6 9 6 6 6-6" />,
  "chevron-left": <path d="m15 18-6-6 6-6" />,
  "chevron-right": <path d="m9 18 6-6-6-6" />,
  "chevron-up": <path d="m18 15-6-6-6 6" />,
  x: (<><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>),
  menu: (<><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h16" /></>),
  check: <path d="M20 6 9 17l-5-5" />,
  search: (<><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>),
  plus: (<><path d="M12 5v14" /><path d="M5 12h14" /></>),
  "arrow-right": (<><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>),
  "arrow-left": (<><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></>),
  user: (<><circle cx="12" cy="8" r="4" /><path d="M5 21c0-4 3-6 7-6s7 2 7 6" /></>),
  users: (<><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-3.5 2.7-5.5 6-5.5s6 2 6 5.5" /><path d="M16 4a3.5 3.5 0 0 1 0 7" /><path d="M17.5 14.7c2.1.6 3.5 2.1 3.5 4.3" /></>),
  calendar: (<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4" /><path d="M16 3v4" /><path d="M3 10h18" /></>),
  "calendar-clock": (<><rect x="3" y="5" width="14" height="16" rx="2" /><path d="M8 3v4" /><path d="M14 3v4" /><path d="M3 10h14" /><circle cx="17.5" cy="17.5" r="4" /><path d="M17.5 16v1.5l1 1" /></>),
  "calendar-days": (<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4" /><path d="M16 3v4" /><path d="M3 10h18" /><path d="M8 14h.01" /><path d="M12 14h.01" /><path d="M16 14h.01" /><path d="M8 17h.01" /><path d="M12 17h.01" /></>),
  clock: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 8v4l2.5 2.5" /></>),
  flask: (<><path d="M9 3h6" /><path d="M10 3v6L5 19a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-10V3" /><path d="M7.5 15h9" /></>),
  book: (<><path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2Z" /><path d="M19 17H6a2 2 0 0 0-2 2" /></>),
  "file-check": (<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5" /><path d="m9.5 15 2 2 3.5-4" /></>),
  "file-text": (<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5" /><path d="M9 13h6" /><path d="M9 17h4" /></>),
  chart: (<><path d="M4 5v14h16" /><path d="m7 15 3.5-5 3 3 4.5-7" /></>),
  "trending-up": (<><path d="m3 17 6-6 4 4 8-8" /><path d="M17 7h4v4" /></>),
  "circle-check": (<><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.5 2.5 2.5 4.5-5" /></>),
  "circle-dashed": (<><path d="M10.2 4.1a8.4 8.4 0 0 1 3.6 0" /><path d="M16.8 6a8.4 8.4 0 0 1 2.2 2.4" /><path d="M19.9 10.2a8.4 8.4 0 0 1 0 3.6" /><path d="M18 16.8a8.4 8.4 0 0 1-2.4 2.2" /><path d="M13.8 19.9a8.4 8.4 0 0 1-3.6 0" /><path d="M7.2 18a8.4 8.4 0 0 1-2.2-2.4" /><path d="M4.1 13.8a8.4 8.4 0 0 1 0-3.6" /><path d="M6 7.2a8.4 8.4 0 0 1 2.4-2.2" /></>),
  help: (<><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.5a2.4 2.4 0 0 1 4.7.8c0 1.4-2.3 1.9-2.3 3.2" /><path d="M12 17h.01" /></>),
  info: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5" /><path d="M12 8h.01" /></>),
  "alert-triangle": (<><path d="M12 3.5 2.5 20h19L12 3.5Z" /><path d="M12 10v4" /><path d="M12 17h.01" /></>),
  play: <path d="m7 4 13 8-13 8Z" />,
  send: (<><path d="M21.5 12 3 11.5l7.5-7.5" /><path d="M3 11.5 21.5 12 10.5 20.5 3 11.5Z" /></>),
  "bookmark-plus": (<><path d="M6 3h12v18l-6-4.5L6 21Z" /><path d="M12 7v6" /><path d="M9 10h6" /></>),
  paperclip: (<><path d="m21 11.5-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-2.8-2.8L15.5 6.4" /></>),
  list: (<><path d="M8 6h13" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M3.5 6h.01" /><path d="M3.5 12h.01" /><path d="M3.5 18h.01" /></>),
  h3: (<><path d="M4 6v12" /><path d="M12 6v12" /><path d="M4 12h8" /><path d="M16 11a2 2 0 1 1 2.5 2 2 2 0 1 1-2.4 2.8c0-2 3-3 4.9-4" /></>),
  lightbulb: (<><path d="M9 18h6" /><path d="M10 21h4" /><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2.2h5c.1-1 .5-1.7 1.1-2.2A6 6 0 0 0 12 3Z" /></>),
  "log-out": (<><path d="M9 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></>),
  copy: (<><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>),
  download: (<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /><path d="M12 15V3" /></>),
  boxes: (<><rect x="3" y="13" width="8" height="8" rx="1" /><rect x="13" y="13" width="8" height="8" rx="1" /><rect x="8" y="3" width="8" height="8" rx="1" /></>),
  box: (<><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18" /><path d="M3 15h18" /></>),
  cpu: (<><rect x="5" y="5" width="14" height="14" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 2v3" /><path d="M15 2v3" /><path d="M9 19v3" /><path d="M15 19v3" /><path d="M2 9h3" /><path d="M2 15h3" /><path d="M19 9h3" /><path d="M19 15h3" /></>),
  server: (<><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" /><path d="M7 7.5h.01" /><path d="M7 16.5h.01" /></>),
  monitor: (<><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8" /><path d="M12 17v4" /></>),
  activity: <path d="M3 12h4l3 8 4-16 3 8h4" />,
  gauge: (<><path d="M20.5 14a8.5 8.5 0 1 0-17 0" /><path d="M12 14l4-5" /></>),
  refresh: (<><path d="M20 11A8 8 0 0 0 5.6 6.6L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.4 4.4L20 16" /><path d="M20 20v-4h-4" /></>),
  shield: (<><path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10Z" /><path d="m9 12 2 2 4-4.5" /></>),
  timer: (<><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 1.5" /><path d="M9 2h6" /></>),
  message: (<><path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" /></>),
  settings: (<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V11a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4Z" /></>),
  external: (<><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" /></>),
};

export interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export function Icon({ name, size = 15, className, style }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" className={className} style={style}>
      {paths[name]}
    </svg>
  );
}
