export function effectiveGrade(first: number | null, second?: number | null): number {
  const base = first ?? 0;
  return second == null ? base : Math.max(base, Math.min(second, 60));
}
export function meanGrade(scores: number[]): number | null {
  return scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length : null;
}
