/* Demonstration records. Final scores are teacher-confirmed, not raw AI suggestions. */
(() => {
  if (page !== 'analytics') return;
  const names = ['林雨桐','周明轩','陈思远','李若溪','张子涵','刘浩然'];
  const experiments = [
    {id:'regression',title:'线性回归与梯度下降',scores:[88,52,76,null,45,92],second:[null,78,null,null,60,null],completed:5},
    {id:'cleaning',title:'数据清洗与特征工程',scores:[92,68,86,56,null,74],second:[null,null,null,48,82,null],completed:5},
    {id:'evaluation',title:'模型评估与交叉验证',scores:[80,null,90,42,58,84],second:[null,59,null,72,54,null],completed:5},
  ];
  const score = (e,i) => e.scores[i] === null ? 0 : e.scores[i];
  const actual = (e,i) => e.second[i] === null ? score(e,i) : Math.max(score(e,i),Math.min(e.second[i],60));
  const select = document.querySelector('select[aria-label="统计范围"]');
  select.innerHTML = '<option value="all">全部实验</option>'+experiments.map(e=>`<option value="${e.id}">${e.title}</option>`).join('');
  const metric = document.querySelector('.metrics');
  // Replace static analysis with one consistent source for filters, scores and retakes.
  let node = metric.nextElementSibling;
  while(node && !node.matches('footer')) { const next=node.nextElementSibling;node.remove();node=next; }
  const host=document.createElement('div');metric.after(host);
  const storage='teacher-prototype-retake-schedules';
  const schedules=()=>JSON.parse(localStorage.getItem(storage)||'[]');
  const chosen=()=>select.value==='all'?experiments:experiments.filter(e=>e.id===select.value);
  const mean=values=>values.reduce((a,b)=>a+b,0)/values.length;
  const fmt=n=>n.toFixed(1);
  const render=()=>{
    const selected=chosen();
    const all=selected.flatMap(e=>names.map((_,i)=>actual(e,i)));
    const missing=selected.reduce((n,e)=>n+e.scores.filter(s=>s===null).length,0);
    const pass=all.filter(s=>s>=60).length;
    metric.innerHTML=[['平均成绩',fmt(mean(all)),`${all.length} 个应提交任务，未提交计 0 分`],['及格率',fmt(pass/all.length*100)+'%','按实际成绩达到 60 分计算'],['未提交',String(missing),'按 0 分纳入统计'],['不及格任务',String(all.length-pass),'实际成绩低于 60 分']].map(([label,n,sub])=>`<div class="metric"><span class="muted">${label}</span><strong>${n}</strong><small>${sub}</small></div>`).join('');
    host.innerHTML=`<div class="note">${select.value==='all'?'全部实验平均分按所有学生、所有应提交实验的实际成绩计算':'当前实验平均分按全部应提交学生的实际成绩计算'}；未提交按 0 分。实际成绩 = max（首次成绩，min（第二次教师确认分数，60））。以下均为规则演示数据。</div>`+
    panel('各实验成绩',table(['实验','应提交','未提交','平均实际成绩',''],selected.map(e=>[e.title,names.length,e.scores.filter(s=>s===null).length,fmt(mean(names.map((_,i)=>actual(e,i)))),`<button data-retake="${e.id}">安排不及格学生重做</button>`])))+
    panel(select.value==='all'?'学生各实验平均成绩':'学生实验成绩',table(['学生','首次成绩','第二次成绩','实际成绩',''],names.map((name,i)=>[name,select.value==='all'?fmt(mean(selected.map(e=>score(e,i)))):selected[0].scores[i]===null?'未提交 · 0':score(selected[0],i),select.value==='all'?'按各实验分别核算':selected[0].second[i]??'未重做',fmt(mean(selected.map(e=>actual(e,i)))),link('student','个人数据','')])))+
    panel('成绩计算明细',table(['学生','实验','首次成绩','第二次教师确认分','实际成绩'],selected.flatMap(e=>names.map((name,i)=>[name,e.title,e.scores[i]===null?'未提交 · 0':e.scores[i],e.second[i]??'—',actual(e,i)]))))+
    panel('重新发布计划',schedules().length?table(['实验','重新开放','截止时间','人数','状态'],schedules().map(s=>[s.title,s.start.replace('T',' '),s.end.replace('T',' '),s.students.length,'待重新发布（演示）'])):'<p class="muted">尚未安排重做</p>');
    host.querySelectorAll('[data-retake]').forEach(b=>b.onclick=()=>openRetake(experiments.find(e=>e.id===b.dataset.retake)));
  };
  function openRetake(e){
    const eligible=names.map((name,i)=>({name,i})).filter(r=>e.second[r.i]===null&&score(e,r.i)<60);
    document.querySelector('#dialog-title').textContent='安排不及格学生重做';
    document.querySelector('#dialog-body').innerHTML=`<form id="retake-form" class="form"><p>${e.title}</p><small>仅选择尚未重做、首次低于 60 分的学生，未提交按 0 分</small><div>${eligible.length?eligible.map(r=>`<label><span><input type="checkbox" name="students" value="${r.i}" checked> ${r.name} · ${score(e,r.i)} 分${e.scores[r.i]===null?'（未提交）':''}</span></label>`).join(''):'<p>当前没有符合条件的学生</p>'}</div><label>重新开放时间<input type="datetime-local" name="start" required></label><label>重新提交截止时间<input type="datetime-local" name="end" required></label><div class="note">第二次成绩先封顶 60 分，再与首次成绩取较大值。第二次截止后未提交按 0 分。评分仍须教师确认。</div><button type="submit" class="primary" ${eligible.length?'':'disabled'}>保存重新发布计划</button><small>本地原型仅保存计划，不会定时触发真实发布</small></form>`;
    document.querySelector('#dialog').showModal();
    document.querySelector('#retake-form').onsubmit=event=>{
      event.preventDefault();const form=event.target;const ids=[...form.querySelectorAll('[name=students]:checked')].map(c=>+c.value);
      if(!ids.length)return toast('请选择重做学生');
      if(new Date(form.elements.start.value)<=new Date())return toast('重新开放时间必须晚于当前时间');
      if(form.elements.end.value<=form.elements.start.value)return toast('截止时间必须晚于开放时间');
      const rows=schedules();
      if(rows.some(s=>s.experiment===e.id&&s.students.some(i=>ids.includes(i))))return toast('所选学生已有重做计划，请勿重复安排');
      rows.push({experiment:e.id,title:e.title,start:form.elements.start.value,end:form.elements.end.value,students:ids});localStorage.setItem(storage,JSON.stringify(rows));
      document.querySelector('#dialog').close();render();toast('重新发布计划已保存（演示）');
    };
  }
  select.onchange=render;render();
})();

