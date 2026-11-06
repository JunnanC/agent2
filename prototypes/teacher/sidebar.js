/* Sidebar refinement; unslop by @heydamir, CC BY 4.0. */
(() => {
  const sidebar = document.querySelector('aside');
  const paths = [
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    '<path d="M12 5C8 2 4 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1Z"/><path d="M12 5v15"/>',
    '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  ];
  const svg = content => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${content}</svg>`;
  sidebar.id = 'teacher-sidebar';
  sidebar.querySelectorAll('nav a').forEach((a, i) => {
    const label = a.textContent;
    a.title = label;
    a.setAttribute('aria-label', label);
    a.innerHTML = svg(paths[i]) + `<span class="nav-label">${label}</span>`;
  });
  const brand = sidebar.querySelector('.brand');
  const brandText = document.createElement('span');
  brandText.className = 'brand-text';
  brandText.innerHTML = brand.innerHTML;
  brand.replaceChildren(brandText);
  const mark = document.createElement('span');
  mark.className = 'compact-brand';
  mark.textContent = '教';
  mark.title = '教学实验平台';
  brand.prepend(mark);
  const toggle = document.createElement('button');
  toggle.className = 'sidebar-toggle';
  toggle.setAttribute('aria-controls', 'teacher-sidebar');
  const storageKey = 'edu.teacher.prototype.sidebar-collapsed';
  let collapsed = false;
  try { collapsed = localStorage.getItem(storageKey) === 'true'; } catch {}
  const update = () => {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    const label = collapsed ? '展开导航栏' : '收起导航栏';
    toggle.title = label;
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.innerHTML = svg(`<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m${collapsed ? '4-12 3 3-3 3' : '3-6-3 3 3 3'}"/>`) + `<span class="toggle-label">${label}</span>`;
  };
  toggle.onclick = () => {
    collapsed = !collapsed;
    try { localStorage.setItem(storageKey, String(collapsed)); } catch {}
    update();
  };
  brand.append(toggle);
  update();
})();
