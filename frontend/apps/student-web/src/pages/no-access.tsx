import { EmptyState } from "@edu/ui";

export function NoAccess() {
  return (
    <EmptyState
      title="没有查看权限"
      hint="当前会话无法访问这个页面。请确认你在正确的门户登录，或联系教师/平台管理员。"
      icon="shield"
      action={<a className="btn primary" href="/">返回首页</a>}
    />
  );
}
