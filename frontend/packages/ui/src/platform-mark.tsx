export function PlatformMark({ size = 28 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
    <path d="M10 29a8 8 0 0 1-1-15.9A11 11 0 0 1 30 12a8.5 8.5 0 0 1 1 17" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    <path d="M17 14h6m-5 0v8l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9v-8" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
    <path d="M16 28h8l2 4H14z" fill="currentColor" />
    <circle cx="20" cy="25" r="1" fill="currentColor" />
  </svg>;
}
