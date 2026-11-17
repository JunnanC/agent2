/** Keep the ordinal outside the editable name, while preserving the existing API title format. */
export function chapterLabel(position: number): string {
  if (!Number.isSafeInteger(position) || position < 1) return "新章节";
  if (position > 9999) return `第${position}章`;
  const digits = "零一二三四五六七八九";
  const units = ["千", "百", "十", ""];
  let text = "";
  let zero = false;
  [1000, 100, 10, 1].forEach((divisor, index) => {
    const digit = Math.floor(position / divisor) % 10;
    if (digit) {
      if (zero) text += "零";
      text += digits.charAt(digit) + (units[index] ?? "");
      zero = false;
    } else if (text && position % divisor) zero = true;
  });
  return `第${text.replace(/^一十/, "十")}章`;
}

export function chapterName(title: string): string {
  return title.replace(/^第[零〇一二三四五六七八九十百千万两\d]+章[\s　、.．:：—-]*/, "").trim();
}

export function chapterTitle(position: number, name: string): string {
  return `${chapterLabel(position)} ${chapterName(name)}`.trim();
}
