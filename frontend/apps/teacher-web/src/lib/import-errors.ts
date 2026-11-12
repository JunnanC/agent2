export function importErrorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const messages = Object.entries(error as Record<string, unknown>).map(([field, code]) => {
      if (code === "invalid_answer_set") return "正确答案不在已填写的选项中";
      if (field === "correct_option_ids") return "正确答案格式不正确";
      if (typeof code === "string") return `${field}：${code}`;
      return `${field} 数据有误`;
    });
    if (messages.length) return messages.join("；");
  }
  return "导入数据有误";
}
