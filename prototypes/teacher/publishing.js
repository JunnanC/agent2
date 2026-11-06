/* Local HTML workflow demonstration; no production requests are made. */
(() => {
  const key = 'teacher-prototype-experiments';
  const read = () => JSON.parse(localStorage.getItem(key) || '[]');
  const write = rows => localStorage.setItem(key, JSON.stringify(rows));
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const params = new URLSearchParams(location.search);
  if (page === 'templates') {
    const create = document.querySelector('a[href="editor.html"]');
    if (create) create.href = 'editor.html?new=1';
    const tbody = document.querySelector('tbody');
    read().forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${escape(row.title)}</td><td>v1.0</td><td>${row.checked ? '预检通过' : '草稿'}</td><td>本地保存</td><td><a href="editor.html?id=${row.id}">编辑</a> · <a href="publishing.html?experiment=${row.id}">发布实验</a></td>`;
      tbody.append(tr);
    });
  }
  if (page === 'editor') {
    const fields = [...document.querySelectorAll('main .form input,main .form textarea')];
    let id = params.get('id');
    const existing = read().find(r => r.id === id);
    let checked = existing?.checked || false;
    if (existing) fields.forEach((field, i) => field.value = existing.fields[i] ?? field.value);
    if (params.has('new')) {
      fields.forEach(field => field.value = '');
      fields[0].placeholder = '填写实验名称';
    }
    const save = () => {
      if (!fields[0].value.trim()) { fields[0].focus(); toast('请填写实验名称'); return null; }
      id ||= String(Date.now());
      const row = {id, title: fields[0].value.trim(), fields: fields.map(f => f.value), checked};
      write([...read().filter(r => r.id !== id), row]);
      history.replaceState(null, '', `editor.html?id=${id}`);
      return row;
    };
    fields.forEach(field => field.addEventListener('input', () => { checked = false; }));
    document.querySelector('[data-save]').onclick = () => { if (save()) toast('实验草稿已保存'); };
    document.querySelector('[data-precheck]').onclick = e => {
      if (!fields[0].value.trim()) return toast('请先填写实验名称');
      checked = true;
      save();
      e.target.textContent = '预检通过（演示）';
      toast('预检通过，可配置发布');
    };
    document.querySelectorAll('.panel a[href="publishing.html"]').forEach(a => {
      a.textContent = '配置并发布此实验';
      a.onclick = e => { e.preventDefault(); const row = save(); if (row) location.href = `publishing.html?experiment=${row.id}`; };
    });
  }
  if (page !== 'publishing') return;
  const pubKey = 'teacher-prototype-publications';
  const pubs = () => JSON.parse(localStorage.getItem(pubKey) || '[]');
  const persist = rows => localStorage.setItem(pubKey, JSON.stringify(rows));
  const tbody = document.querySelector('tbody');
  const render = () => {
    tbody.querySelectorAll('[data-local-publication]').forEach(r => r.remove());
    pubs().forEach(row => {
      const tr = document.createElement('tr'); tr.dataset.localPublication = row.id;
      tr.innerHTML = `<td>${escape(row.title)}</td><td>0 / ${row.status === '已发布' ? '48' : '0'}</td><td>${escape(row.deadline.replace('T',' '))}</td><td>${row.status}</td><td>${row.status === '草稿' ? `<button data-check="${row.id}">运行发布预检</button>` : row.status === '待发布' ? `<button class="primary" data-publish="${row.id}">发布实验</button>` : '<a href="publication.html">查看发布与评审</a>'}</td>`;
      tbody.prepend(tr);
    });
    tbody.querySelectorAll('[data-check]').forEach(b => b.onclick = () => {
      persist(pubs().map(r => r.id === b.dataset.check ? {...r, status:'待发布'} : r)); render(); toast('发布预检通过（演示），请确认发布');
    });
    tbody.querySelectorAll('[data-publish]').forEach(b => b.onclick = () => {
      const row = pubs().find(r => r.id === b.dataset.publish);
      document.querySelector('#dialog-title').textContent = '确认发布实验';
      document.querySelector('#dialog-body').innerHTML = `<p>将“${escape(row.title)}”发布给本课程全体 48 名学生</p><p>截止时间：${escape(row.deadline.replace('T',' '))}</p><button class="primary" id="publish-confirm">确认发布</button>`;
      document.querySelector('#dialog').showModal();
      document.querySelector('#publish-confirm').onclick = () => {
        persist(pubs().map(r => r.id === row.id ? {...r,status:'已发布'} : r));
        document.querySelector('#dialog').close(); render(); toast('实验已发布（本地原型演示）');
      };
    });
  };
  const open = () => {
    const experiments = read();
    const choices = experiments.length ? experiments : [{id:'example',title:'线性回归与梯度下降'}];
    document.querySelector('#dialog-title').textContent = '配置实验发布';
    document.querySelector('#dialog-body').innerHTML = `<form id="publish-form" class="form"><label>实验版本<select name="experiment">${choices.map(r => `<option value="${r.id}" ${r.id === params.get('experiment') ? 'selected' : ''}>${escape(r.title)} · v1.0</option>`).join('')}</select></label><label>发布名称<input name="title" required></label><label>发布对象<select><option>本课程全体学生 · 48 人</option></select></label><label>开放时间<input type="datetime-local" name="start" required></label><label>截止时间<input type="datetime-local" name="deadline" required></label><label>评分标准<select><option>实现正确性 40 / 结果分析 35 / 完整性 25</option></select></label><label><span><input type="checkbox" checked required> 需要提交实验报告</span></label><p class="muted">创建草稿后运行预检，再确认发布</p><button type="submit" class="primary">创建发布草稿</button><small>本地原型演示，不发送正式发布请求</small></form>`;
    const form = document.querySelector('#publish-form');
    const update = () => { form.elements.title.value = choices.find(r => r.id === form.elements.experiment.value).title; };
    update(); form.elements.experiment.onchange = update;
    form.onsubmit = e => {
      e.preventDefault();
      if (form.elements.deadline.value <= form.elements.start.value) return toast('截止时间必须晚于开放时间');
      persist([...pubs(),{id:String(Date.now()),experiment:form.elements.experiment.value,title:form.elements.title.value.trim(),start:form.elements.start.value,deadline:form.elements.deadline.value,status:'草稿'}]);
      document.querySelector('#dialog').close(); render(); toast('发布草稿已创建，请运行发布预检');
    };
    document.querySelector('#dialog').showModal();
  };
  document.querySelector('[data-dialog="创建实验发布"]').onclick = open;
  render();
  if (params.has('experiment')) open();
})();
