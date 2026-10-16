import assert from 'node:assert/strict';
import { test } from 'node:test';
import { auditRows, filterRows, governanceRows, toCsv } from './data.ts';

test('搜索与状态筛选共同生效，支持空结果', () => {
  assert.equal(filterRows(governanceRows, '管理员', '高').length, 1);
  assert.equal(filterRows(governanceRows, '不存在', '高').length, 0);
  assert.equal(filterRows(governanceRows, '', '中').length, 2);
});
test('时间筛选排除昨天，Trace 搜索可定位记录', () => {
  assert.equal(filterRows(auditRows, '', 'all', 1).length, 3);
  assert.equal(filterRows(auditRows, 'TR_E491F12B').length, 1);
});
test('CSV 保留中文、引号和换行，转义公式前缀', () => {
  const csv = toCsv(['动作'], [['更新"配置'], ['=1+1'], ['多行\n内容']]);
  assert.ok(csv.startsWith('\ufeff'));
  assert.ok(csv.includes('"更新""配置"'));
  assert.ok(csv.includes('"\'=1+1"'));
  assert.ok(csv.includes('"多行\n内容"'));
});
