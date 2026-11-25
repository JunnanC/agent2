import { Link } from "react-router-dom";
import { TeacherIcon } from "./teacher-b";

export function TeacherHeader({ name, unread = 0, onNotifications, onLogout }: {
  name: string; unread?: number; onNotifications: () => void; onLogout?: () => void;
}) {
  return <header className="top"><div className="wrap top-inner">
    <Link className="brand" to="/"><span className="brand-mark"><TeacherIcon name="brand" /></span>教学实验平台</Link>
    <div className="top-end">
      <button className="bell" type="button" aria-label={unread ? `通知中心，${unread} 条未读` : "通知中心"} title="通知中心" onClick={onNotifications}><TeacherIcon name="bell" /></button>
      {onLogout ? <details className="profile-menu"><summary className="profile"><span className="avatar" aria-hidden="true">{name.slice(0, 1)}</span><span className="profile-name">{name}</span></summary>
        <button className="btn" type="button" onClick={onLogout}>退出登录</button>
      </details> : <span className="profile"><span className="avatar" aria-hidden="true">{name.slice(0, 1)}</span>{name}</span>}
    </div>
  </div></header>;
}
