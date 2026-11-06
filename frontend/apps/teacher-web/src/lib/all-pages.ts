/** Aggregate only complete responses; never silently display a truncated mean. */
export async function allPages<T>(fetchPage: (page: number) => Promise<{ rows: T[]; total?: number }>): Promise<T[]> {
  const result: T[] = [];
  for (let page = 1; page <= 10000; page += 1) {
    const response = await fetchPage(page);
    result.push(...response.rows);
    if (!response.rows.length || (response.total != null && result.length >= response.total)) return result;
    if (response.total == null) throw new Error("接口缺少总数，无法保证全量统计完整性");
  }
  throw new Error("数据量超过安全读取范围，请使用服务端汇总接口");
}
