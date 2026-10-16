const portalConfig={
  student:{label:'\u5b66\u751f\u95e8\u6237',domain:'student.edu.local',name:'\u6797\u77e5\u590f',role:'\u5b66\u751f · \u8ba1\u7b97\u673a\u7f51\u7edc',avatar:'\u6797',home:'student-home',nav:[['\u6982\u89c8','student-home'],['\u6211\u7684\u8bfe\u7a0b','student-courses'],['\u52a0\u5165\u8bfe\u7a0b','student-join-courses'],['\u5b9e\u9a8c\u4efb\u52a1','student-tasks'],['\u901a\u77e5','student-notifications']]},
  teacher:{label:'\u6559\u5e08\u95e8\u6237',domain:'teacher.edu.local',name:'\u5468\u8001\u5e08',role:'\u6559\u5e08 · \u8bfe\u7a0b\u8d1f\u8d23\u4eba',avatar:'\u5468',home:'teacher-home',nav:[['\u6559\u5b66\u6982\u89c8','teacher-home'],{label:'\u8bfe\u7a0b\u4e0e\u5b9e\u9a8c',items:[['\u6211\u7684\u8bfe\u7a0b','teacher-courses'],['\u9009\u8bfe\u7ba1\u7406','teacher-enrollments'],['\u5b9e\u9a8c\u8bbe\u8ba1','teacher-templates'],['\u5b9e\u9a8c\u53d1\u5e03','teacher-publishing']]},{label:'\u5b66\u751f\u4e0e\u8bc4\u5ba1',items:[['\u5b66\u751f\u8fc7\u7a0b','teacher-progress'],['\u8bc4\u5ba1\u4e2d\u5fc3','teacher-reviews']]},['\u6559\u5b66\u5206\u6790','teacher-analytics']]},
  admin:{label:'\u5e73\u53f0\u7ba1\u7406',domain:'admin.edu.local',name:'\u5e73\u53f0\u7ba1\u7406\u5458',role:'\u7cfb\u7edf\u6cbb\u7406',avatar:'\u7ba1',home:'admin-home',nav:[['\u5e73\u53f0\u6982\u89c8','admin-home'],['\u6cbb\u7406\u5de5\u4f5c','admin-governance'],['\u8d44\u6e90\u6cbb\u7406','admin-resources'],['\u5f02\u5e38\u4e2d\u5fc3','admin-incidents'],['\u5f02\u5e38\u4e0e\u5ba1\u8ba1','admin-audit']]}
};
let currentPortal='student';
const charts={};
const $=selector=>document.querySelector(selector);
const html=String.raw;
let profileOpen=false;
const studentCourseCatalog=[
  {id:'course-network-2026',code:'CS-NET-2026',title:'计算机网络',summary:'从网络基础到故障定位，完成 DNS、路由与端口连通性实验。',owner_name:'周老师',enrollment_mode:'OPEN',capacity:60,active_enrollment_count:42,enrollment_end:'2026-10-20',progress:'3 / 5 个实验',last_activity:'今天完成 DNS 检查点',enrollment_status:'ACTIVE'},
  {id:'course-database-2026',code:'CS-DB-2026',title:'数据库系统',summary:'围绕索引、事务与查询优化，掌握数据库性能分析方法。',owner_name:'陈老师',enrollment_mode:'APPROVAL',capacity:45,active_enrollment_count:28,enrollment_end:'2026-10-24',progress:'2 / 4 个实验',last_activity:'昨天查看实验说明',enrollment_status:'ACTIVE'},
  {id:'course-cloud-2026',code:'CS-CLOUD-2026',title:'云原生实践',summary:'通过容器网络与服务编排实验，建立云原生应用运维基础。',owner_name:'黄老师',enrollment_mode:'OPEN',capacity:40,active_enrollment_count:31,enrollment_end:'2026-10-28',progress:'4 / 6 个实验',last_activity:'教师已批注报告',enrollment_status:'ACTIVE'},
  {id:'course-os-2026',code:'CS-OS-2026',title:'操作系统原理',summary:'学习进程、文件系统与系统调用，完成配套实验和阶段报告。',owner_name:'李老师',enrollment_mode:'OPEN',capacity:null,active_enrollment_count:36,enrollment_end:'2026-11-03',progress:'尚未开始',last_activity:'暂无活动'},
  {id:'course-ai-2026',code:'CS-AI-2026',title:'人工智能导论',summary:'从机器学习基础到模型评估，完成数据分析与智能应用实践。',owner_name:'王老师',enrollment_mode:'APPROVAL',capacity:50,active_enrollment_count:37,enrollment_end:'2026-11-05',progress:'尚未开始',last_activity:'暂无活动'},
  {id:'course-software-2026',code:'CS-SE-2026',title:'软件工程项目实践',summary:'以团队项目贯穿需求分析、协作开发、测试与交付流程。',owner_name:'赵老师',enrollment_mode:'APPROVAL',capacity:48,active_enrollment_count:32,enrollment_end:'2026-10-26',progress:'申请已提交',last_activity:'等待教师审核',enrollment_status:'PENDING'}
];
let selectedJoinCourseId=null;
let studentJoinTab='discover';
let studentJoinSearch='';
let studentJoinMode='all';

function calendarDeadlineOffset(days,hour=18){
  const date=new Date();
  date.setDate(date.getDate()+days);
  date.setHours(hour,0,0,0);
  return date.toISOString();
}
const studentCalendarTasks=[
  {id:'task-linux-network',title:'Linux 网络故障排查',course:'计算机网络',effective_deadline:calendarDeadlineOffset(1),status:'IN_PROGRESS',progress:68},
  {id:'task-database-index',title:'数据库索引优化',course:'数据库系统',effective_deadline:calendarDeadlineOffset(3,23),status:'ASSIGNED',progress:0},
  {id:'task-container-network',title:'容器网络基础',course:'云原生实践',effective_deadline:calendarDeadlineOffset(3,23),status:'REPORT_DRAFT',progress:82},
  {id:'task-completed-dns',title:'DNS 基础检查',course:'计算机网络',effective_deadline:calendarDeadlineOffset(0,17),status:'COMPLETED',progress:100},
  {id:'task-review-tcp',title:'TCP 拥塞控制',course:'计算机网络',effective_deadline:calendarDeadlineOffset(2),status:'UNDER_REVIEW',progress:100}
];
const studentCalendarActionableStatuses=new Set(['ASSIGNED','PROVISIONING','READY','IN_PROGRESS','REPORT_DRAFT','REJECTED','FAILED']);
let studentCalendarSelectedDate=null;
const currentCalendarDate=new Date();
let studentCalendarCursor=new Date(currentCalendarDate.getFullYear(),currentCalendarDate.getMonth(),1);

function calendarDateKey(value){
  const text=String(value||'');
  if(/^\d{4}-\d{2}-\d{2}$/.test(text))return text;
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return null;
  return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
}
function buildDeadlineCalendarModel(tasks=studentCalendarTasks){
  return tasks.filter(task=>task?.effective_deadline&&studentCalendarActionableStatuses.has(task.status)).reduce((groups,task)=>{
    const date=calendarDateKey(task.effective_deadline);
    if(date)(groups[date]??=[]).push(task);
    return groups;
  },{});
}
function calendarDateLabel(dateKey){
  const date=new Date(`${dateKey}T12:00:00`);
  const weekdays=['日','一','二','三','四','五','六'];
  return `${date.getMonth()+1} 月 ${date.getDate()} 日（周${weekdays[date.getDay()]}）`;
}
function studentCalendarSummary(){
  const groups=buildDeadlineCalendarModel();
  const dates=Object.keys(groups).sort();
  const count=Object.values(groups).reduce((total,tasks)=>total+tasks.length,0);
  if(!dates.length)return {count,nearest:'暂无截止日期'};
  const date=new Date(`${dates[0]}T12:00:00`);
  return {count,nearest:`最近截止 ${date.getMonth()+1} 月 ${date.getDate()} 日`};
}
function calendarTaskStatusLabel(status){
  return {ASSIGNED:'待开始',PROVISIONING:'准备环境',READY:'已准备',IN_PROGRESS:'进行中',REPORT_DRAFT:'报告草稿',REJECTED:'需修改',FAILED:'需处理'}[status]||'待完成';
}
function renderStudentTaskRow(task){
  const dateKey=calendarDateKey(task.effective_deadline);
  const statusStyle=task.status==='IN_PROGRESS'||task.status==='REPORT_DRAFT'?'good':'warn';
  const action=task.id==='task-linux-network'?'<button class="btn sm primary" type="button" onclick="openWorkbench()">进入工作台</button>':`<button class="btn sm" type="button" data-task-id="${escapeCalendarHtml(task.id)}" onclick="openStudentTaskDetail(this.dataset.taskId)">查看详情</button>`;
  return `<div class="task-row" id="student-task-${escapeCalendarHtml(task.id)}"><div><a class="task-title task-title-link" href="#student-task-detail" data-task-id="${escapeCalendarHtml(task.id)}" onclick="event.preventDefault();openStudentTaskDetail(this.dataset.taskId)">${escapeCalendarHtml(task.title)}</a><div class="task-meta">${escapeCalendarHtml(task.course)} · 完成度 ${escapeCalendarHtml(task.progress)}%</div></div><div class="task-side"><div class="task-deadline"><span class="status ${statusStyle}">${calendarTaskStatusLabel(task.status)}</span><br>${dateKey?`截止 ${calendarDateLabel(dateKey)}`:'暂无截止日期'}</div>${action}</div></div>`;
}
function escapeCalendarHtml(value){
  return String(value??'').replace(/[&<>"']/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
}
function positionStudentCalendarPopover(){
  const popover=$('#studentCalendarPopover');
  const selected=$('#studentCalendarGrid .calendar-day.selected');
  const shell=$('.calendar-shell');
  if(!popover||popover.hidden||!selected||!shell||typeof selected.getBoundingClientRect!=='function')return;
  const buttonRect=selected.getBoundingClientRect();
  const shellRect=shell.getBoundingClientRect();
  const maxLeft=Math.max(12,shell.clientWidth-popover.offsetWidth-12);
  const left=Math.min(Math.max(12,buttonRect.left-shellRect.left+buttonRect.width/2-popover.offsetWidth/2),maxLeft);
  let top=buttonRect.bottom-shellRect.top+8;
  if(top+popover.offsetHeight>shell.clientHeight-8)top=buttonRect.top-shellRect.top-popover.offsetHeight-8;
  top=Math.max(8,top);
  popover.style.left=`${left}px`;
  popover.style.top=`${top}px`;
}
function selectStudentCalendarDate(dateKey){
  studentCalendarSelectedDate=studentCalendarSelectedDate===dateKey?null:dateKey;
  renderStudentCalendar();
}
function closeStudentCalendarPopover(){
  studentCalendarSelectedDate=null;
  renderStudentCalendar();
}
function changeStudentCalendarMonth(offset){
  studentCalendarCursor=new Date(studentCalendarCursor.getFullYear(),studentCalendarCursor.getMonth()+offset,1);
  studentCalendarSelectedDate=null;
  renderStudentCalendar();
}
function openStudentCalendarTask(taskId){
  const task=studentCalendarTasks.find(item=>item.id===taskId);
  if(!task)return;
  if(task.id==='task-linux-network')openWorkbench();
  else {
    closeStudentCalendarPopover();
    go('student-tasks');
    setTimeout(()=>{
      const target=document.getElementById(`student-task-${task.id}`);
      if(!target)return;
      target.scrollIntoView({behavior:'smooth',block:'center'});
      target.classList.add('calendar-target');
      setTimeout(()=>target.classList.remove('calendar-target'),2600);
    },80);
  }
}
function renderStudentCalendar(){
  const grid=$('#studentCalendarGrid');
  const popover=$('#studentCalendarPopover');
  const monthLabel=$('#studentCalendarMonthLabel');
  if(!grid||!popover||!monthLabel)return;
  const year=studentCalendarCursor.getFullYear();
  const month=studentCalendarCursor.getMonth();
  const groups=buildDeadlineCalendarModel();
  const firstDay=(new Date(year,month,1).getDay()+6)%7;
  const daysInMonth=new Date(year,month+1,0).getDate();
  const todayKey=calendarDateKey(new Date());
  monthLabel.textContent=`${year} 年 ${month+1} 月`;
  const cells=[];
  for(let index=0;index<firstDay;index++)cells.push('<div class="calendar-day empty" aria-hidden="true"></div>');
  for(let day=1;day<=daysInMonth;day++){
    const dateKey=`${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    const tasks=groups[dateKey]||[];
    const isSelected=dateKey===studentCalendarSelectedDate;
    const isToday=dateKey===todayKey;
    cells.push(`<button class="calendar-day${isSelected?' selected':''}${isToday?' today':''}" type="button" onclick="selectStudentCalendarDate('${dateKey}')" aria-pressed="${isSelected}" aria-label="${calendarDateLabel(dateKey)}，${tasks.length?`${tasks.length} 项任务到期`:'无任务到期'}"><span class="calendar-day-number">${day}</span>${tasks.length?`<span class="calendar-count">${tasks.length}</span>`:''}</button>`);
  }
  grid.innerHTML=cells.join('');
  const selectedTasks=studentCalendarSelectedDate?(groups[studentCalendarSelectedDate]||[]):[];
  if(!studentCalendarSelectedDate||!selectedTasks.length){
    popover.hidden=true;
    popover.innerHTML='';
    popover.removeAttribute('style');
    return;
  }
  popover.hidden=false;
  popover.innerHTML=`<div class="calendar-popover-head"><div><span class="eyebrow">${calendarDateLabel(studentCalendarSelectedDate)}</span><strong>${selectedTasks.length} 项课程实验任务</strong></div><button class="icon-btn" type="button" onclick="closeStudentCalendarPopover()" aria-label="关闭任务提示">${icon('x')}</button></div><div class="calendar-task-list">${selectedTasks.map(task=>`<button class="calendar-task" type="button" onclick="openStudentCalendarTask('${escapeCalendarHtml(task.id)}')"><span class="calendar-task-copy"><strong>${escapeCalendarHtml(task.title)}</strong><small>${escapeCalendarHtml(task.course)} · 完成度 ${escapeCalendarHtml(task.progress)}%</small></span><span class="calendar-task-meta"><span class="status ${task.status==='IN_PROGRESS'||task.status==='REPORT_DRAFT'?'good':'warn'}">${calendarTaskStatusLabel(task.status)}</span><i data-lucide="chevron-right"></i></span></button>`).join('')}</div>`;
  lucide.createIcons();
  positionStudentCalendarPopover();
}

function icon(name){return `<i data-lucide="${name}"></i>`}
function metric(label,value,sub,iconName='activity'){return html`<div class="metric"><div class="mrow"><span class="label">${label}</span><span class="metric-icon">${icon(iconName)}</span></div><strong>${value}</strong><span class="subtle">${sub}</span></div>`}
function tableRows(rows){return rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}
function renderNav(){
  const portal=portalConfig[currentPortal];
  $('#domain').textContent=portal.domain;$('#userName').textContent=portal.name;$('#userRole').textContent=portal.role;$('#avatar').textContent=portal.avatar;
  $('#profilePopoverName').textContent=portal.name;$('#profilePopoverRole').textContent=portal.role;
  $('#nav').innerHTML=portal.nav.map((item,index)=>{
    if(Array.isArray(item))return `<button data-go="${item[1]}">${item[0]}</button>`;
    const groupId=`nav-group-${index}`;
    return `<div class="nav-group" data-nav-group="${groupId}"><button class="nav-group-toggle" type="button" aria-expanded="false" aria-controls="${groupId}-menu">${item.label}${icon('chevron-down')}</button><div class="nav-group-menu" id="${groupId}-menu" role="menu">${item.items.map(([label,id])=>`<button type="button" role="menuitem" data-go="${id}">${label}</button>`).join('')}</div></div>`;
  }).join('');
  $('#nav').querySelectorAll('[data-go]').forEach(button=>button.addEventListener('click',()=>go(button.dataset.go)));
  $('#nav').querySelectorAll('.nav-group-toggle').forEach(button=>button.addEventListener('click',()=>toggleNavGroup(button.closest('.nav-group'))));
  lucide.createIcons();syncNav();
}
function toggleNavGroup(group){if(!group)return;const willOpen=!group.classList.contains('open');closeNavGroups();if(willOpen){group.classList.add('open');group.querySelector('.nav-group-toggle')?.setAttribute('aria-expanded','true')}}
function closeNavGroups(){document.querySelectorAll('#nav .nav-group').forEach(group=>{group.classList.remove('open');group.querySelector('.nav-group-toggle')?.setAttribute('aria-expanded','false')})}
function go(id){closeNavGroups();document.querySelectorAll('.screen').forEach(screen=>screen.classList.toggle('active',screen.id===id));syncNav();stripPageIntros();window.scrollTo({top:0,behavior:'smooth'});setTimeout(()=>{lucide.createIcons();resizeCharts()},30)}
function syncNav(){const id=document.querySelector('.screen.active')?.id;document.querySelectorAll('#nav [data-go]').forEach(button=>button.classList.toggle('active',button.dataset.go===id));document.querySelectorAll('#nav .nav-group').forEach(group=>group.classList.toggle('active',Boolean(group.querySelector(`[data-go="${id}"]`))))}
function setPortal(portal){currentPortal=portal;$('#portalSelect').value=portal;renderNav();go(portalConfig[portal].home)}
function toast(message){const element=$('#toast');element.textContent=message;element.classList.add('show');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>element.classList.remove('show'),2200)}
function setProfileOpen(open){const popover=$('#profilePopover');const button=$('#profileMenuButton');if(!popover||!button)return;profileOpen=open;popover.hidden=!open;popover.classList.toggle('open',open);button.setAttribute('aria-expanded',String(open));if(open)lucide.createIcons()}
function toggleProfileDrawer(){setProfileOpen(!profileOpen)}
function closeProfileDrawer(){setProfileOpen(false)}
function handleProfileAction(action){closeProfileDrawer();if(action==='settings')go('settings');else if(action==='help')toast('帮助中心（演示）');else if(action==='feedback')toast('已打开意见反馈（演示）')}
function openModal(id){$('#'+id)?.classList.add('open');lucide.createIcons()}
function closeModal(id){$('#'+id)?.classList.remove('open')}
function backdrop(event,id){if(event.target.id===id)closeModal(id)}
function openWorkbench(){window.location.href='student-workbench.html'}
function editorTab(key,element){document.querySelectorAll('.editor-tab').forEach(tab=>tab.style.display='none');$('#ed-'+key).style.display='block';document.querySelectorAll('.step').forEach(step=>step.classList.remove('active'));element?.classList.add('active')}
function selectResource(element,name){document.querySelectorAll('.resource').forEach(resource=>resource.classList.remove('selected'));element.classList.add('selected');document.querySelectorAll('.resource-name').forEach(node=>node.textContent=name);toast('已选择 '+name+'，保存后需要重新预检')}
function filterTable(input,id){const query=input.value.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(row=>row.style.display=row.innerText.toLowerCase().includes(query)?'':'none')}
function createTemplate(){const name=$('#templateName').value.trim();if(!name){toast('请填写模板名称');return}closeModal('create');go('template-editor');toast('模板草稿已创建，进入版本配置')}

function studentCourseModeLabel(course){return course.enrollment_mode==='APPROVAL'?'申请审核':'直接加入'}
function studentCourseStatusLabel(status){return {ACTIVE:'已加入',PENDING:'审核中',REJECTED:'未通过',WITHDRAWN:'已撤回',DROPPED:'已退出',REMOVED:'已移出'}[status]||''}
function studentCourseStatusStyle(status){return status==='ACTIVE'?'good':status==='PENDING'?'warn':status?'neutral':'blue'}
function studentCourseDeadline(course){const date=new Date(`${course.enrollment_end}T12:00:00`);return Number.isNaN(date.getTime())?'未设置':`${date.getMonth()+1}月${date.getDate()}日`}
function studentCourseCatalogTabCounts(){return {discover:studentCourseCatalog.filter(course=>!['ACTIVE','PENDING'].includes(course.enrollment_status)).length,enrollments:studentCourseCatalog.filter(course=>course.enrollment_status).length}}
function renderStudentJoinCourses(){
  const counts=studentCourseCatalogTabCounts();
  $('#student-join-courses').innerHTML=html`<div class="crumb">学生门户　/　加入课程</div><div class="head"><div><h1>加入课程</h1><p>浏览本学期开放课程，查看课程要求并提交加入申请。</p></div><span class="status neutral join-course-term"><i data-lucide="calendar-days"></i> 2026 秋季学期</span></div><section class="panel join-course-intro"><span class="join-course-intro-icon"><i data-lucide="book-open-check"></i></span><div class="join-course-intro-copy"><strong>找到适合你的课程</strong><p>部分课程可直接加入，部分课程需要教师审核。使用课程邀请码时，可在申请表单中填写。</p></div><div class="join-course-intro-steps"><span><b>01</b> 浏览课程</span><i data-lucide="chevron-right"></i><span><b>02</b> 查看要求</span><i data-lucide="chevron-right"></i><span><b>03</b> 提交申请</span></div></section><div class="join-course-tabs" role="tablist" aria-label="课程列表"><button class="join-course-tab ${studentJoinTab==='discover'?'active':''}" type="button" role="tab" aria-selected="${studentJoinTab==='discover'}" onclick="setStudentJoinTab('discover')">发现课程 <span>${counts.discover}</span></button><button class="join-course-tab ${studentJoinTab==='enrollments'?'active':''}" type="button" role="tab" aria-selected="${studentJoinTab==='enrollments'}" onclick="setStudentJoinTab('enrollments')">我的课程与申请 <span>${counts.enrollments}</span></button></div><section class="panel join-course-browser"><div class="join-course-toolbar"><div class="join-course-search"><i data-lucide="search"></i><input id="studentJoinSearch" type="search" value="${escapeCalendarHtml(studentJoinSearch)}" placeholder="搜索课程名称或课程代码" aria-label="搜索课程"></div><label class="join-course-filter-label" for="studentJoinMode">加入方式</label><select id="studentJoinMode" class="field join-course-filter"><option value="all" ${studentJoinMode==='all'?'selected':''}>全部方式</option><option value="OPEN" ${studentJoinMode==='OPEN'?'selected':''}>直接加入</option><option value="APPROVAL" ${studentJoinMode==='APPROVAL'?'selected':''}>申请审核</option></select><span class="join-course-result-count" id="studentJoinResultCount"></span></div><div class="join-course-grid" id="studentJoinResults"></div></section>`;
  $('#studentJoinSearch').addEventListener('input',event=>{studentJoinSearch=event.target.value;renderStudentJoinResults()});
  $('#studentJoinMode').addEventListener('change',event=>{studentJoinMode=event.target.value;renderStudentJoinResults()});
  renderStudentJoinResults();
  stripPageIntros();
  document.querySelector('#student-join-courses .join-course-intro')?.remove();
}
function renderStudentJoinResults(){
  const results=$('#studentJoinResults');
  if(!results)return;
  const query=studentJoinSearch.trim().toLowerCase();
  const courses=studentCourseCatalog.filter(course=>studentJoinTab==='discover'?!['ACTIVE','PENDING'].includes(course.enrollment_status):Boolean(course.enrollment_status)).filter(course=>studentJoinMode==='all'||course.enrollment_mode===studentJoinMode).filter(course=>!query||`${course.title} ${course.code} ${course.summary} ${course.owner_name}`.toLowerCase().includes(query));
  $('#studentJoinResultCount').textContent=studentJoinTab==='discover'?`${courses.length} 门可申请课程`:`${courses.length} 门课程`;
  if(!courses.length){results.innerHTML=`<div class="join-course-empty"><span class="join-course-empty-icon"><i data-lucide="search-x"></i></span><strong>${studentJoinTab==='discover'?'没有找到匹配的开放课程':'暂无匹配的课程记录'}</strong><p>${studentJoinTab==='discover'?'试试其他关键词或加入方式筛选。':'调整筛选条件，或先去发现课程。'}</p></div>`;lucide.createIcons();return}
  results.innerHTML=courses.map(course=>{
    const status=course.enrollment_status;
    const capacity=course.capacity?`${course.active_enrollment_count} / ${course.capacity} 人`:`${course.active_enrollment_count} 人已加入`;
    const secondaryButton=['ACTIVE','PENDING'].includes(status)?'':`<button type="button" class="btn sm" onclick="openStudentCourseDetail('${course.id}')">课程详情</button>`;
    const primaryButton=status==='ACTIVE'?`<button type="button" class="btn sm" onclick="go('student-courses')">查看课程</button>`:status==='PENDING'?`<button type="button" class="btn sm" onclick="openStudentCourseDetail('${course.id}')">查看申请</button>`:`<button type="button" class="btn sm primary" onclick="openStudentCourseApplication('${course.id}')">申请加入</button>`;
    return `<article class="join-course-card"><div class="join-course-card-top"><span class="join-course-subject-icon"><i data-lucide="book-open"></i></span><div class="join-course-card-status">${status?`<span class="status ${studentCourseStatusStyle(status)}">${studentCourseStatusLabel(status)}</span>`:`<span class="status ${course.enrollment_mode==='OPEN'?'good':'blue'}">${studentCourseModeLabel(course)}</span>`}</div></div><div class="join-course-code">${escapeCalendarHtml(course.code)}</div><h2>${escapeCalendarHtml(course.title)}</h2><p class="join-course-summary">${escapeCalendarHtml(course.summary)}</p><div class="join-course-meta"><span><i data-lucide="user-round"></i>${escapeCalendarHtml(course.owner_name)}</span><span><i data-lucide="users-round"></i>${escapeCalendarHtml(capacity)}</span><span><i data-lucide="calendar-clock"></i>截止 ${studentCourseDeadline(course)}</span></div><div class="join-course-card-footer"><span class="join-course-mode-note">${status==='PENDING'?'申请已提交，等待教师审核':status==='ACTIVE'?escapeCalendarHtml(course.progress):course.enrollment_mode==='OPEN'?'加入后立即生效':'提交后等待教师审核'}</span><div class="join-course-card-actions">${secondaryButton}${primaryButton}</div></div></article>`;
  }).join('');
  lucide.createIcons();
}
function setStudentJoinTab(tab){studentJoinTab=tab;renderStudentJoinCourses();}
function getStudentCourse(courseId){return studentCourseCatalog.find(course=>course.id===courseId)}
function renderStudentCourseModal(course,view='detail'){
  const modal=$('#studentCourseModal');
  if(!modal||!course)return;
  const status=course.enrollment_status;
  const capacity=course.capacity?`${course.active_enrollment_count} / ${course.capacity} 人`:`${course.active_enrollment_count} 人已加入`;
  const modalContent=$('#studentCourseModalContent');
  if(view==='application'){
    modalContent.innerHTML=`<div class="join-course-modal-heading"><span class="eyebrow">课程加入申请</span><button class="icon-btn" type="button" onclick="closeModal('studentCourseModal')" aria-label="关闭"><i data-lucide="x"></i></button></div><h2>${escapeCalendarHtml(course.title)}</h2><p class="join-course-modal-subtitle">${escapeCalendarHtml(course.code)} · ${studentCourseModeLabel(course)}</p><div class="join-course-application-note"><i data-lucide="${course.enrollment_mode==='OPEN'?'circle-check':'info'}"></i><span>${course.enrollment_mode==='OPEN'?'提交后将直接加入课程。':'提交后将进入审核队列，教师审核通过后即可加入。'}</span></div><form class="join-course-form" onsubmit="submitStudentCourseApplication(event)"><label class="form-label" for="courseInvitationCode">课程邀请码 <span>选填</span></label><input class="field" id="courseInvitationCode" name="invitation_code" maxlength="128" placeholder="如教师提供了邀请码，请填写"><label class="form-label" for="courseApplicationMessage">申请说明 <span>选填</span></label><textarea class="field" id="courseApplicationMessage" name="application_message" rows="3" maxlength="2000" placeholder="向教师介绍你的学习目标或加入原因"></textarea><div class="join-course-modal-actions"><button type="button" class="btn" onclick="openStudentCourseDetail('${course.id}')">返回课程详情</button><button type="submit" class="btn primary">${course.enrollment_mode==='OPEN'?'确认加入课程':'提交加入申请'}</button></div></form>`;
  }else if(view==='result'){
    const active=status==='ACTIVE';
    modalContent.innerHTML=`<div class="join-course-result-state ${active?'success':'pending'}"><span class="join-course-result-icon"><i data-lucide="${active?'circle-check':'clock-3'}"></i></span><span class="eyebrow">${active?'课程加入成功':'申请已提交'}</span><h2>${active?'已加入课程':'等待教师审核'}</h2><p>${active?`你现在可以前往“我的课程”查看${escapeCalendarHtml(course.title)}的课程内容。`:`${escapeCalendarHtml(course.title)}的加入申请已提交，审核结果会显示在“我的课程与申请”中。`}</p><div class="join-course-modal-actions"><button type="button" class="btn" onclick="closeModal('studentCourseModal')">稍后查看</button><button type="button" class="btn primary" onclick="closeModal('studentCourseModal');go('student-join-courses');setStudentJoinTab('enrollments')">查看我的课程与申请</button></div></div>`;
  }else{
    modalContent.innerHTML=`<div class="join-course-modal-heading"><span class="eyebrow">课程详情</span><button class="icon-btn" type="button" onclick="closeModal('studentCourseModal')" aria-label="关闭"><i data-lucide="x"></i></button></div><div class="join-course-detail-title"><span class="join-course-subject-icon"><i data-lucide="book-open"></i></span><div><span class="join-course-code">${escapeCalendarHtml(course.code)}</span><h2>${escapeCalendarHtml(course.title)}</h2></div></div><p class="join-course-detail-summary">${escapeCalendarHtml(course.summary)}</p><div class="join-course-detail-grid"><div><span>课程负责人</span><strong>${escapeCalendarHtml(course.owner_name)}</strong></div><div><span>加入方式</span><strong>${studentCourseModeLabel(course)}</strong></div><div><span>当前人数</span><strong>${escapeCalendarHtml(capacity)}</strong></div><div><span>申请截止</span><strong>${studentCourseDeadline(course)}</strong></div></div>${status?`<div class="join-course-application-note"><i data-lucide="${status==='PENDING'?'clock-3':'circle-check'}"></i><span>${status==='PENDING'?'申请已提交，等待教师审核。':'你已加入这门课程。'}</span></div>`:`<div class="join-course-application-note"><i data-lucide="${course.enrollment_mode==='OPEN'?'zap':'info'}"></i><span>${course.enrollment_mode==='OPEN'?'提交申请后直接加入。':'需要教师审核，通过后即可加入。'}</span></div>`}<div class="join-course-modal-actions"><button type="button" class="btn" onclick="closeModal('studentCourseModal')">关闭</button>${status==='ACTIVE'?`<button type="button" class="btn primary" onclick="closeModal('studentCourseModal');go('student-courses')">查看我的课程</button>`:status==='PENDING'?'':`<button type="button" class="btn primary" onclick="openStudentCourseApplication('${course.id}')">${course.enrollment_mode==='OPEN'?'加入课程':'申请加入'}</button>`}</div>`;
  }
  modal.classList.add('open');
  lucide.createIcons();
}
function openStudentCourseDetail(courseId){renderStudentCourseModal(getStudentCourse(courseId),'detail')}
function openStudentCourseApplication(courseId){selectedJoinCourseId=courseId;renderStudentCourseModal(getStudentCourse(courseId),'application')}
function submitStudentCourseApplication(event){
  event.preventDefault();
  const course=getStudentCourse(selectedJoinCourseId);
  if(!course)return;
  const form=new FormData(event.currentTarget);
  course.application_message=String(form.get('application_message')||'').trim();
  course.invitation_code=String(form.get('invitation_code')||'').trim();
  course.enrollment_status=course.enrollment_mode==='OPEN'?'ACTIVE':'PENDING';
  if(course.enrollment_status==='ACTIVE')course.active_enrollment_count+=1;
  course.last_activity=course.enrollment_status==='ACTIVE'?'刚刚加入课程':'申请已提交，等待教师审核';
  course.progress=course.enrollment_status==='ACTIVE'?'尚未开始':'申请已提交';
  renderStudentCourseModal(course,'result');
  renderStudentJoinCourses();
}
function mountStudentCourseModal(){$('#modalRoot').insertAdjacentHTML('beforeend','<div class="modal-backdrop" id="studentCourseModal" onclick="backdrop(event,\'studentCourseModal\')"><div class="modal join-course-modal"><div id="studentCourseModalContent"></div></div></div>')}

function renderStudent(){
  const calendarSummary=studentCalendarSummary();
  $('#student-home').innerHTML=html`
    <div class="crumb">学生门户　/　概览</div>
    <div class="metric-group">${metric('进行中的实验','3','其中 1 个待提交','flask-conical')}${metric('本周学习时长','6.5 h','比上周多 48 分钟','clock-3')}${metric('待完成任务',String(calendarSummary.count),calendarSummary.nearest,'calendar-clock')}${metric('已获评审','12','最近一次评分 92 分','file-check-2')}</div>
    <div class="grid two section student-home-overview"><section class="panel calendar-panel" aria-labelledby="studentCalendarTitle"><div class="panel-title calendar-panel-title"><div><h2 id="studentCalendarTitle">任务日历</h2><span class="subtle">按截止日期查看待完成任务</span></div><div class="calendar-month-nav"><button class="icon-btn" type="button" onclick="changeStudentCalendarMonth(-1)" aria-label="上个月">${icon('chevron-left')}</button><strong id="studentCalendarMonthLabel">2026 年 10 月</strong><button class="icon-btn" type="button" onclick="changeStudentCalendarMonth(1)" aria-label="下个月">${icon('chevron-right')}</button></div></div><div class="calendar-shell"><div class="calendar-main"><div class="calendar-weekdays"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div><div class="calendar-grid" id="studentCalendarGrid"></div></div><div class="calendar-popover" id="studentCalendarPopover" hidden aria-live="polite"></div></div></section><section class="panel"><div class="panel-title"><h2>本周学习节奏</h2><span class="subtle">近 7 天</span></div><div class="chart short"><canvas id="studentTrend"></canvas></div></section></div>
    <section class="panel section"><div class="panel-title"><h2>我的课程</h2></div><div class="table-wrap"><table class="table"><thead><tr><th>课程</th><th>进度</th><th>最近活动</th><th>状态</th></tr></thead><tbody>${tableRows([['计算机网络','<div class="progress"><span style="width:68%"></span></div>','今天完成 1 个检查点','<span class="status good">进行中</span>'],['数据库系统','<div class="progress"><span style="width:41%"></span></div>','昨天查看实验说明','<span class="status warn">待开始</span>'],['云原生实践','<div class="progress"><span style="width:82%"></span></div>','教师已批注报告','<span class="status blue">评审中</span>']])}</tbody></table></div></section>`;
  renderStudentCalendar();
  $('#student-courses').innerHTML=html`<div class="crumb">学生门户　/　我的课程</div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>课程</th><th>课程负责人</th><th>实验进度</th><th>最近活动</th><th></th></tr></thead><tbody>${tableRows([['计算机网络','周老师','3 / 5 个实验','今天完成 DNS 检查点','<button class="btn sm primary" onclick="go(\'student-tasks\')">进入课程</button>'],['数据库系统','陈老师','2 / 4 个实验','昨天查看实验说明','<button class="btn sm" onclick="go(\'student-tasks\')">进入课程</button>'],['云原生实践','黄老师','4 / 4 个实验','报告评审中','<button class="btn sm" onclick="go(\'student-tasks\')">查看课程</button>']])}</tbody></table></div></section>`;
  $('#student-tasks').innerHTML=html`<div class="crumb">学生门户　/　实验任务</div><div class="head"><div><h1>实验任务</h1><p>按截止时间查看需要开始、继续或提交的实验。</p></div><div class="actions"><button class="btn">全部状态 ${icon('chevron-down')}</button><button class="btn">全部课程 ${icon('chevron-down')}</button></div></div><section class="panel"><div class="task-list">${studentCalendarTasks.filter(task=>studentCalendarActionableStatuses.has(task.status)).map(renderStudentTaskRow).join('')}</div></section>`;
  renderStudentJoinCourses();
}

function renderTeacher(){
  $('#teacher-home').innerHTML=html`<div class="crumb">教师门户　/　教学概览</div><div class="head"><div><h1>教学概览</h1><p>掌握课程实验完成情况，把时间留给真正需要关注的学生。</p></div><div class="actions"><button class="btn" onclick="go('teacher-analytics')">查看教学分析 ${icon('arrow-right')}</button><button class="btn primary" onclick="openModal('create')">新建实验模板 ${icon('plus')}</button></div></div><div class="metric-group">${metric('授课课程','4','本学期活跃课程','book-open')}${metric('进行中实验','12','3 个版本待发布','flask-conical')}${metric('待评审报告','28','较昨日减少 6 份','files')}${metric('班级完成率','76%','较上周提升 8%','chart-no-axes-combined')}</div><div class="grid two section"><section class="panel"><div class="panel-title"><h2>班级实验进度</h2><span class="subtle">近 7 天</span></div><div class="chart"><canvas id="teacherTrend"></canvas></div></section><section class="panel"><div class="panel-title"><h2>需要你处理</h2><span class="status warn">4 项</span></div><div class="item"><div><strong>网络故障排查 · 报告评审</strong><small>12 份报告 · 最早提交于今天 09:20</small></div><button class="btn sm" onclick="go('teacher-reviews')">进入</button></div><div class="item"><div><strong>Linux 实验模板 · 版本预检</strong><small>第 3 章资源规格需要更新</small></div><button class="btn sm" onclick="go('template-editor')">查看</button></div><div class="item"><div><strong>数据库实验 · 发布窗口</strong><small>准备发布给 2024 级 2 班</small></div><button class="btn sm primary" onclick="toast('发布流程（演示）')">发布</button></div></section></div><section class="panel section"><div class="panel-title"><h2>近期课程</h2><button class="btn sm" onclick="go('teacher-courses')">全部课程 ${icon('arrow-right')}</button></div><div class="table-wrap"><table class="table"><thead><tr><th>课程</th><th>班级</th><th>实验完成率</th><th>待评审</th><th>状态</th></tr></thead><tbody>${tableRows([['计算机网络','2024 级 1、2 班','76%','12 份','<span class="status good">进行中</span>'],['数据库系统','2023 级 3 班','64%','8 份','<span class="status warn">需关注</span>'],['云原生实践','2024 级 1 班','88%','8 份','<span class="status blue">评审中</span>']])}</tbody></table></div></section>`;
  $('#teacher-courses').innerHTML=html`<div class="crumb">教师门户　/　我的课程</div><div class="head"><div><h1>我的课程</h1><p>从课程进入实验模板、发布和评审。</p></div><button class="btn primary" onclick="toast('新建课程（演示）')">新建课程 ${icon('plus')}</button></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>课程</th><th>班级</th><th>模板数量</th><th>学生数</th><th>本周完成率</th><th></th></tr></thead><tbody>${tableRows([['计算机网络','2024 级 1、2 班','6','96','76%','<button class="btn sm" onclick="go(\'teacher-templates\')">管理实验</button>'],['数据库系统','2023 级 3 班','4','48','64%','<button class="btn sm" onclick="go(\'teacher-templates\')">管理实验</button>'],['云原生实践','2024 级 1 班','5','42','88%','<button class="btn sm" onclick="go(\'teacher-templates\')">管理实验</button>']])}</tbody></table></div></section>`;
  $('#teacher-templates').innerHTML=html`<div class="crumb">教师门户　/　实验设计</div><div class="head"><div><h1>实验模板</h1><p>模板与版本分离管理，已发布版本不会被草稿修改覆盖。</p></div><button class="btn primary" onclick="openModal('create')">新建实验模板 ${icon('plus')}</button></div><section class="panel"><div class="panel-title"><h2>计算机网络</h2><div class="actions"><button class="btn sm">全部状态 ${icon('chevron-down')}</button><button class="btn sm">搜索模板 ${icon('search')}</button></div></div><div class="table-wrap"><table class="table"><thead><tr><th>模板名称</th><th>当前版本</th><th>发布状态</th><th>最近修改</th><th></th></tr></thead><tbody>${tableRows([['Linux 网络故障排查','v1.3 · 6 个章节','<span class="status good">已发布</span>','今天 14:26','<button class="btn sm primary" onclick="go(\'template-editor\')">配置模板</button>'],['HTTP 服务调试','v0.8 · 4 个章节','<span class="status warn">草稿</span>','昨天 16:10','<button class="btn sm" onclick="go(\'template-editor\')">继续编辑</button>'],['容器网络基础','v2.1 · 5 个章节','<span class="status blue">评审中</span>','10 月 8 日','<button class="btn sm" onclick="go(\'template-editor\')">查看版本</button>']])}</tbody></table></div></section>`;
  $('#teacher-analytics').innerHTML=html`<div class="crumb">教师门户　/　教学分析</div><div class="head"><div><h1>教学分析</h1><p>用完成、提交和评审数据定位需要调整的课程环节。</p></div><button class="btn">本学期 ${icon('chevron-down')}</button></div><div class="metric-group">${metric('平均完成率','76%','较上周 +8%','chart-no-axes-combined')}${metric('平均实验时长','42 min','较上周 -5 min','timer')}${metric('报告一次通过率','81%','较上月 +4%','file-check-2')}${metric('需要关注的章节','3','集中在资源配置','triangle-alert')}</div><div class="grid equal section"><section class="panel"><div class="panel-title"><h2>完成率趋势</h2><span class="subtle">近 30 天</span></div><div class="chart"><canvas id="analyticsTrend"></canvas></div></section><section class="panel"><div class="panel-title"><h2>各实验完成情况</h2></div><div class="item"><div><strong>Linux 网络故障排查</strong><small>96 名学生 · 82% 完成</small></div><span class="status good">稳定</span></div><div class="item"><div><strong>HTTP 服务调试</strong><small>96 名学生 · 61% 完成</small></div><span class="status warn">需关注</span></div><div class="item"><div><strong>容器网络基础</strong><small>42 名学生 · 88% 完成</small></div><span class="status good">稳定</span></div></section></div>`;
  renderTeacherReviewCenter();
}

function renderAdmin(){
  $('#admin-home').innerHTML=html`<div class="crumb">平台管理　/　平台概览</div><div class="head"><div><h1>平台概览</h1><p>用一组统一的运行数据观察平台健康、资源使用与治理事项。</p></div><button class="btn" onclick="go('admin-audit')">查看操作日志 ${icon('arrow-right')}</button></div><div class="metric-group">${metric('运行工作区','128','健康运行 124','boxes')}${metric('CPU 使用率','62%','集群总量 32 vCPU','cpu')}${metric('内存使用率','71%','可用内存 42 GB','memory-stick')}${metric('治理待办','17','3 项高优先级','clipboard-check')}</div><div class="grid two section"><section class="panel"><div class="panel-title"><h2>资源使用趋势</h2><select class="portal-switch"><option>最近 24 小时</option><option>最近 7 天</option></select></div><div class="legend"><span><b style="background:#2f7069"></b>CPU</span><span><b style="background:#9b7d54"></b>内存</span></div><div class="chart"><canvas id="resourceTrend"></canvas></div></section><section class="panel"><div class="panel-title"><h2>待处理治理事项</h2><button class="btn sm" onclick="go('admin-governance')">查看全部</button></div><div class="item"><div><strong>教师资格待审核</strong><small>12 位申请人 · 最早 2 天前</small></div><button class="btn sm" onclick="toast('进入资格审核（演示）')">处理</button></div><div class="item"><div><strong>镜像扫描异常</strong><small>3 个镜像需要复核</small></div><button class="btn sm" onclick="toast('进入镜像治理（演示）')">查看</button></div><div class="item"><div><strong>运行时容量告警</strong><small>集群 B · 可用 CPU 低于阈值</small></div><button class="btn sm" onclick="openModal('governance')">排查</button></div></section></div><div class="grid equal section"><section class="panel"><div class="panel-title"><h2>运行与异常趋势</h2><span class="subtle">近 7 天</span></div><div class="chart short"><canvas id="incidentTrend"></canvas></div></section><section class="panel"><div class="panel-title"><h2>平台服务健康</h2><span class="subtle">最近检查 14:32</span></div><div class="item"><div><strong>API 服务</strong><small>响应正常 · p95 142 ms</small></div><span class="status good">健康</span></div><div class="item"><div><strong>数据库</strong><small>连接池正常</small></div><span class="status good">健康</span></div><div class="item"><div><strong>运行时集群</strong><small>集群 B 容量偏低</small></div><span class="status warn">关注</span></div></section></div>`;
  $('#admin-governance').innerHTML=html`<div class="crumb">平台管理　/　治理工作</div><div class="head"><div><h1>治理工作</h1><p>集中处理用户资格、镜像、运行时和安全策略等平台事项。</p></div><button class="btn">事项类型 ${icon('chevron-down')}</button></div><section class="panel"><div class="panel-title"><h2>待处理事项</h2><span class="status warn">17 项</span></div><div class="table-wrap"><table class="table"><thead><tr><th>事项</th><th>范围</th><th>优先级</th><th>创建时间</th><th>负责人</th><th></th></tr></thead><tbody>${tableRows([['教师资格待审核','用户与资格','<span class="status bad">高</span>','2 天前','管理员 A','<button class="btn sm primary" onclick="toast(\'进入审核（演示）\')">处理</button>'],['镜像扫描异常','镜像与资源','<span class="status warn">中</span>','昨天 18:20','管理员 B','<button class="btn sm" onclick="toast(\'进入镜像治理（演示）\')">查看</button>'],['运行时容量告警','运行时与实例','<span class="status bad">高</span>','今天 08:10','管理员 A','<button class="btn sm" onclick="openModal(\'governance\')">排查</button>'],['异常实验任务','安全与审计','<span class="status warn">中</span>','今天 10:02','未分配','<button class="btn sm" onclick="toast(\'进入异常任务排查（演示）\')">分派</button>']])}</tbody></table></div></section>`;
  $('#admin-audit').innerHTML=html`<div class="crumb">平台管理　/　异常与审计</div><div class="head"><div><h1>异常与审计</h1><p>记录平台关键动作，帮助快速定位异常实验与治理变更。</p></div><div class="actions"><button class="btn">近 7 天 ${icon('chevron-down')}</button><button class="btn">导出日志 ${icon('download')}</button></div></div><section class="panel"><div class="panel-title"><h2>操作日志</h2><input class="field" style="max-width:210px" placeholder="搜索操作、用户或资源" oninput="filterTable(this,'auditTable')"></div><div class="table-wrap"><table class="table" id="auditTable"><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>结果</th></tr></thead><tbody>${tableRows([['今天 14:32','管理员 A','更新运行时资源配置','集群 B','<span class="status good">成功</span>'],['今天 13:55','周老师','发布模板版本 v1.3','Linux 网络故障排查','<span class="status good">成功</span>'],['今天 12:18','系统','停止异常实验实例','task_01M4…','<span class="status warn">需复核</span>'],['昨天 19:44','管理员 B','撤回镜像批准状态','Ubuntu Network Lab v2.2','<span class="status good">成功</span>']])}</tbody></table></div></section>`;
}

function renderEditor(){
  $('#template-editor').innerHTML=html`<div class="crumb">教师门户　/　实验设计　/　Linux 网络故障排查</div><div class="head"><div><h1>配置实验模板</h1><p>草稿版本 v1.4 · 修改不会影响已发布版本。</p></div><div class="actions"><button class="btn" onclick="go('teacher-templates')">返回模板列表</button><button class="btn" onclick="openModal('precheck')">运行预检</button><button class="btn primary" onclick="toast('草稿已保存（演示）')">保存草稿</button></div></div><div class="editor"><aside class="panel steps"><div class="step active" onclick="editorTab('basic',this)"><span>01　基础信息</span><span>✓</span></div><div class="step" onclick="editorTab('content',this)"><span>02　内容结构</span><span>✓</span></div><div class="step" onclick="editorTab('runtime',this)"><span>03　运行环境</span><span>!</span></div><div class="step" onclick="editorTab('report',this)"><span>04　报告与评审</span></div><div class="step" onclick="editorTab('publish',this)"><span>05　预检与发布</span></div></aside><section class="panel"><div id="ed-basic" class="editor-tab"><div class="panel-title"><h2>基础信息</h2><span class="status good">已完成</span></div><label class="form-label">模板名称</label><input class="field" value="Linux 网络故障排查"><label class="form-label">实验目标</label><textarea class="field" rows="4">理解常见网络故障定位方法，能够通过命令行完成 DNS、路由和端口连通性检查。</textarea><div class="grid equal"><div><label class="form-label">所属课程</label><select class="field"><option>计算机网络</option></select></div><div><label class="form-label">预计用时</label><input class="field" value="45 分钟"></div></div></div><div id="ed-content" class="editor-tab" style="display:none"><div class="panel-title"><h2>内容结构</h2><span class="status good">6 个章节</span></div><div class="item"><div><strong>1. 实验准备</strong><small>目标、环境检查与注意事项</small></div><button class="btn sm">编辑</button></div><div class="item"><div><strong>2. DNS 故障定位</strong><small>nslookup、dig 与解析链路</small></div><button class="btn sm">编辑</button></div><div class="item"><div><strong>3. 路由与端口检查</strong><small>资源规格需要单独覆盖</small></div><button class="btn sm">编辑</button></div><button class="btn sm" style="margin-top:12px">新增章节 ${icon('plus')}</button></div><div id="ed-runtime" class="editor-tab" style="display:none"><div class="panel-title"><h2>运行环境与资源</h2><span class="status warn">1 项待处理</span></div><div class="alert">教师只能选择已经过平台治理的镜像、资源规格与运行时适配器；发布时系统会固定 digest。</div><label class="form-label">已治理镜像</label><div class="resource selected" onclick="openModal('images')"><span class="radio"></span><div><strong class="resource-name">Ubuntu Network Lab · v2.4</strong><div class="meta"><span>sha256:8f2c…b91</span><span>扫描通过</span><span>已批准</span></div></div><div class="resource-right"><span class="status good">已选择</span></div></div><label class="form-label">运行时适配器</label><select class="field"><option>Docker Sandbox · v3</option></select><div class="grid equal"><div><label class="form-label">默认资源规格</label><select class="field"><option>small · 1 vCPU · 2 GB</option></select></div><div><label class="form-label">网络策略</label><select class="field"><option>课程实验网络 · 允许 DNS</option></select></div></div><label class="form-label">章节资源覆盖</label><div class="item"><div><strong>第 3 章 · 路由与端口检查</strong><small>当前使用 small，建议提升至 medium</small></div><button class="btn sm" onclick="toast('打开章节资源配置（演示）')">配置</button></div></div><div id="ed-report" class="editor-tab" style="display:none"><div class="panel-title"><h2>报告与评审</h2><span class="status good">已完成</span></div><label class="form-label">报告要求</label><textarea class="field" rows="4">提交故障定位过程、关键命令输出和最终修复建议。</textarea><div class="item"><div><strong>自动检查结果纳入评审</strong><small>学生提交前必须通过 8 项检查</small></div><span class="status good">开启</span></div></div><div id="ed-publish" class="editor-tab" style="display:none"><div class="panel-title"><h2>预检与发布</h2><span class="status warn">不可直接发布</span></div><div class="status-line">✓　基础信息完整</div><div class="status-line">✓　镜像治理状态有效</div><div class="status-line" style="color:var(--amber)">!　第 3 章资源规格需要更新</div><div class="status-line">✓　报告与自动检查规则完整</div><button class="btn primary" style="margin-top:12px" onclick="openModal('precheck')">重新运行预检</button></div></section><aside class="panel summary"><div class="panel-title"><h2>版本摘要</h2><span class="status warn">草稿</span></div><div class="sumline"><span>模板</span><strong>Linux 网络故障排查</strong></div><div class="sumline"><span>当前版本</span><strong>v1.4</strong></div><div class="sumline"><span>章节数</span><strong>6</strong></div><div class="sumline"><span>引用课程</span><strong>1 门</strong></div><div class="sumline"><span>最近保存</span><strong>刚刚</strong></div><button class="btn primary" style="width:100%;justify-content:center;margin-top:14px" onclick="openModal('precheck')">运行预检</button></aside></div>`;
}

const studentNotifications=[
  {id:'notice-1',type:'deadline',title:'实验截止提醒',body:'Linux 网络故障排查将在明天 18:00 截止，请完成报告并提交。',time:'10 分钟前',read:false,action:'student-task-detail'},
  {id:'notice-2',type:'review',title:'教师已返回报告',body:'云原生实践第 2 阶段报告收到 2 条批注，建议在进入下一阶段前完成修改。',time:'昨天 16:40',read:false,action:'student-tasks'},
  {id:'notice-3',type:'system',title:'平台维护通知',body:'本周六 02:00—04:00 进行运行时升级，期间不会影响已保存的实验记录。',time:'10 月 10 日',read:true,action:'student-home'},
];
let selectedStudentTaskId='task-linux-network';
const teacherEnrollmentRows=[
  {id:'enroll-1',student:'\u9648\u5b50\u8c6a',course:'\u8ba1\u7b97\u673a\u7f51\u7edc',message:'希望系统学习网络故障定位。',status:'PENDING',time:'今天 09:20'},
  {id:'enroll-2',student:'\u8d75\u4e91\u5e06',course:'\u8ba1\u7b97\u673a\u7f51\u7edc',message:'已有 Linux 基础，希望加入实验班。',status:'PENDING',time:'昨天 18:10'},
  {id:'enroll-3',student:'\u5434\u9759',course:'\u6570\u636e\u5e93\u7cfb\u7edf',message:'申请加入秋季实验课程。',status:'APPROVED',time:'10 月 10 日'},
];
const teacherPublicationRows=[
  {id:'pub-1',name:'Linux 网络故障排查',version:'v1.4',audience:'2024 级 1、2 班',status:'DRAFT',window:'10 月 13 日 09:00 — 10 月 27 日 18:00',tasks:96},
  {id:'pub-2',name:'HTTP 服务调试',version:'v0.8',audience:'2024 级 1 班',status:'PRECHECK',window:'待设置',tasks:48},
  {id:'pub-3',name:'容器网络基础',version:'v2.1',audience:'2023 级 3 班',status:'PUBLISHED',window:'进行中',tasks:42},
];
const teacherReviewSeedRows=[
  {id:'review-1',student:'林知夏',experiment:'Linux 网络故障排查',course:'计算机网络',submitted:'今天 14:26',auto:'通过 8 / 8',status:'PENDING',score:0,annotations:[],decision:null},
  {id:'review-2',student:'陈默',experiment:'HTTP 服务调试',course:'计算机网络',submitted:'今天 11:42',auto:'通过 7 / 8',status:'PENDING',score:0,annotations:[],decision:null},
  {id:'review-3',student:'赵一鸣',experiment:'容器网络基础',course:'云原生实践',submitted:'昨天 17:12',auto:'通过 8 / 8',status:'APPROVED',score:92,annotations:['端口验证过程记录完整。'],decision:'通过'}
];
const teacherReviewRows=(()=>{try{const saved=JSON.parse(localStorage.getItem('edu-agent-teacher-reviews'));return Array.isArray(saved)&&saved.length?saved:teacherReviewSeedRows}catch{return teacherReviewSeedRows}})();
let selectedTeacherReviewId=null;
function persistTeacherReviews(){try{localStorage.setItem('edu-agent-teacher-reviews',JSON.stringify(teacherReviewRows))}catch{}}
function syncSubmittedReportToReview(){try{const submission=JSON.parse(localStorage.getItem('edu-agent-report-submission'));if(!submission)return;const review=teacherReviewRows.find(row=>row.id==='review-1');if(!review)return;review.reportHtml=submission.reportHtml||'';review.submitted=submission.submittedAt||review.submitted;review.reportStatus=submission.status||'PENDING_REVIEW';if(submission.status==='PENDING_REVIEW')review.status='PENDING';if(submission.status==='APPROVED')review.status='APPROVED';if(submission.status==='RETURNED')review.status='RETURNED'}catch{}}
function syncStudentReviewResult(review,decision){
  if(!review)return;
  const message=decision==='RETURNED'?'教师已退回报告，请根据批注修改后重新提交。':`教师已完成评审，本次评分 ${review.score || '待补充'} 分。`;
  try{localStorage.setItem('edu-agent-student-review-result',JSON.stringify({status:decision,score:review.score||0,feedback:review.annotations.join(' '),reviewId:review.id}));const submission=JSON.parse(localStorage.getItem('edu-agent-report-submission')||'null');if(submission&&review.id==='review-1'){submission.status=decision;submission.reviewScore=review.score;submission.feedback=review.annotations;localStorage.setItem('edu-agent-report-submission',JSON.stringify(submission))}}catch{}
  const existing=studentNotifications.find(item=>item.id===`review-${review.id}`);
  if(existing){existing.body=message;existing.read=false;existing.time='刚刚';existing.action='student-task-detail'}
  else studentNotifications.unshift({id:`review-${review.id}`,type:'review',title:decision==='RETURNED'?'报告需要修改':'报告评审完成',body:message,time:'刚刚',read:false,action:'student-task-detail'});
}
function renderTeacherReviewCenter(){
  const target=$('#teacher-reviews');
  if(!target)return;
  syncSubmittedReportToReview();
  persistTeacherReviews();
  target.innerHTML=`<div class="crumb">教师门户　/　评审中心</div><div class="page-actions"><div class="actions"><button class="btn sm review-filter active" data-review-filter="PENDING">待评审</button><button class="btn sm review-filter" data-review-filter="ALL">全部记录</button></div><span class="status warn">${teacherReviewRows.filter(row=>row.status==='PENDING').length} 份待处理</span></div><section class="panel section"><div class="panel-title"><div><h2>报告提交</h2><span class="subtle">先查看提交预览和自动检查，再进入评分。</span></div><input class="field" style="max-width:220px" placeholder="搜索学生或实验" oninput="filterTable(this,'teacherReviewTable')"></div><div class="table-wrap"><table class="table" id="teacherReviewTable"><thead><tr><th>学生</th><th>实验</th><th>提交时间</th><th>自动检查</th><th>状态</th><th></th></tr></thead><tbody>${teacherReviewRows.map(row=>`<tr data-review-status="${row.status}"><td><strong>${row.student}</strong></td><td>${row.experiment}</td><td>${row.submitted}</td><td>${row.auto}</td><td><span class="status ${row.status==='PENDING'?'warn':row.status==='RETURNED'?'bad':'good'}">${row.status==='PENDING'?'待评审':row.status==='RETURNED'?'待修改':'已通过'}</span></td><td><button class="btn sm ${row.status==='PENDING'?'primary':''}" onclick="openTeacherReview('${row.id}')">${row.status==='PENDING'?'开始评审':'查看评审'}</button></td></tr>`).join('')}</tbody></table></div></section><section class="panel section review-detail-panel" id="teacherReview" hidden></section>`;
  document.querySelectorAll('[data-review-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-review-filter]').forEach(item=>item.classList.toggle('active',item===button));document.querySelectorAll('#teacherReviewTable tbody tr').forEach(row=>row.hidden=button.dataset.reviewFilter==='PENDING'&&row.dataset.reviewStatus!=='PENDING')}));
  lucide.createIcons();
}
function openTeacherReview(reviewId){
  const review=teacherReviewRows.find(row=>row.id===reviewId);const target=$('#teacherReview');if(!review||!target)return;
  selectedTeacherReviewId=reviewId;target.hidden=false;target.innerHTML=`<div class="panel-title"><div><h2>${review.student} · ${review.experiment}</h2><span class="subtle">提交预览 · ${review.submitted} · 自动检查 ${review.auto} · 相似度 ${review.similarity||'12%'}</span></div><button class="btn sm" onclick="closeTeacherReview()">返回列表</button></div><div class="review-workspace"><div class="review-preview"><div class="review-section"><span class="eyebrow">报告内容</span><div class="report-submission-copy" id="reviewReportContent">报告内容将在这里显示。</div></div><div class="review-section"><span class="eyebrow">工作区证据</span><div class="evidence-row"><span>执行记录</span><button class="btn sm" onclick="toast('已打开执行记录（演示）')">查看 execution-runs</button></div><div class="evidence-row"><span>工作区快照</span><button class="btn sm" onclick="toast('已打开工作区快照（演示）')">查看 snapshot</button></div><div class="evidence-row"><span>操作回放</span><button class="btn sm" onclick="toast('已打开 operation-replay（演示）')">查看 operation-replay</button></div></div></div><div class="review-form"><div class="review-rubric"><div class="panel-title"><h3>Rubric 评分</h3><span class="status blue">criterion-scores</span></div>${[['定位过程','能够使用证据说明排查路径'],['技术准确性','命令与结论对应'],['报告完整性','模板内容填写完整']].map((item,index)=>`<label class="score-row"><span><strong>${item[0]}</strong><small>${item[1]}</small></span><select class="field" data-criterion="${index}"><option value="0">未评分</option>${[60,70,80,90,100].map(score=>`<option value="${score}" ${review.scores?.[index]===score?'selected':''}>${score} 分</option>`).join('')}</select></label>`).join('')}</div><label class="form-label" for="reviewAnnotation">报告批注</label><textarea class="field" id="reviewAnnotation" rows="4" placeholder="写下需要学生修改或值得肯定的内容"></textarea><div class="annotation-list">${review.annotations.map(annotation=>`<div class="annotation-chip"><i data-lucide="message-square-more"></i>${annotation}</div>`).join('')}</div><div class="review-actions"><button class="btn" onclick="addTeacherReviewAnnotation()">保存批注</button><button class="btn" onclick="saveTeacherReview()">保存评分</button><button class="btn" onclick="decideTeacherReview('RETURNED')">退回修改</button><button class="btn primary" onclick="decideTeacherReview('APPROVED')">通过评审</button></div></div></div>`;const reportContent=$('#reviewReportContent');if(reportContent){const parsed=new DOMParser().parseFromString(review.reportHtml||'', 'text/html');reportContent.textContent=parsed.body.textContent.trim()||'学生尚未提交报告内容。'}target.scrollIntoView({behavior:'smooth',block:'start'});lucide.createIcons();}
function saveTeacherReview(){const review=teacherReviewRows.find(row=>row.id===selectedTeacherReviewId);if(!review)return false;const scores=[...document.querySelectorAll('#teacherReview [data-criterion]')].map(select=>Number(select.value));if(scores.length!==3||scores.some(score=>score<1)){toast('请完成全部 Rubric 评分');return false}review.scores=scores;review.score=Math.round(scores.reduce((total,score)=>total+score,0)/scores.length);persistTeacherReviews();toast(`评分已保存：${review.score} 分`);return true}
function addTeacherReviewAnnotation(){const review=teacherReviewRows.find(row=>row.id===selectedTeacherReviewId);const input=$('#reviewAnnotation');if(!review||!input?.value.trim())return;review.annotations.push(input.value.trim());persistTeacherReviews();openTeacherReview(review.id);toast('批注已保存')}
function decideTeacherReview(decision){const review=teacherReviewRows.find(row=>row.id===selectedTeacherReviewId);if(!review||!saveTeacherReview())return;if(decision==='RETURNED'&&!review.annotations.length){toast('退回前请至少添加一条修改批注');return}review.decision=decision;review.status=decision==='RETURNED'?'RETURNED':'APPROVED';persistTeacherReviews();syncStudentReviewResult(review,decision);renderTeacherReviewCenter();toast(decision==='RETURNED'?'已退回报告并通知学生':'评审已通过并通知学生')}
function closeTeacherReview(){const target=$('#teacherReview');if(target)target.hidden=true;selectedTeacherReviewId=null}

function openStudentCourseDetail(){
  renderStudentCourseDetail();
  stripPageIntros();
  go('student-course-detail');
}
function openStudentTaskDetail(taskId='task-linux-network'){
  selectedStudentTaskId=taskId;
  renderStudentTaskDetail();
  stripPageIntros();
  go('student-task-detail');
}
function markStudentNotificationRead(notificationId){
  const item=studentNotifications.find(notification=>notification.id===notificationId);
  if(!item)return;
  item.read=true;
  renderStudentNotifications();
  stripPageIntros();
  toast('\u5df2\u6807\u8bb0\u4e3a\u5df2\u8bfb');
}
function reviewTeacherEnrollment(enrollmentId,decision){
  const item=teacherEnrollmentRows.find(row=>row.id===enrollmentId);
  if(!item)return;
  item.status=decision==='approve'?'APPROVED':'REJECTED';
  renderTeacherExpandedScreens();
  stripPageIntros();
  toast(decision==='approve'?'\u5df2\u901a\u8fc7\u9009\u8bfe\u7533\u8bf7':'\u5df2\u62d2\u7edd\u9009\u8bfe\u7533\u8bf7');
}
function publishTeacherExperiment(publicationId,action){
  const item=teacherPublicationRows.find(row=>row.id===publicationId);
  if(!item)return;
  item.status=action==='publish'?'PUBLISHED':action==='withdraw'?'WITHDRAWN':'PRECHECK';
  renderTeacherExpandedScreens();
  stripPageIntros();
  toast(action==='publish'?'\u5b9e\u9a8c\u5df2\u53d1\u5e03':action==='withdraw'?'\u5b9e\u9a8c\u5df2\u64a4\u56de':'\u5df2\u91cd\u65b0\u8fd0\u884c\u9884\u68c0');
}
function renderStudentCourseDetail(){
  const target=$('#student-course-detail');
  if(!target)return;
  target.innerHTML=`<div class="crumb">\u5b66\u751f\u95e8\u6237　/　\u6211\u7684\u8bfe\u7a0b　/　\u8ba1\u7b97\u673a\u7f51\u7edc</div><div class="head"><div><h1>\u8ba1\u7b97\u673a\u7f51\u7edc</h1><p>\u4ece\u7ae0\u8282\u3001\u8bfe\u7a0b\u8d44\u6599\u548c\u65e5\u5386\u8fdb\u5165\u6bcf\u4e00\u4e2a\u5b9e\u9a8c\u4efb\u52a1\u3002</p></div><div class="actions"><button class="btn" onclick="go('student-courses')">\u8fd4\u56de\u8bfe\u7a0b</button><button class="btn primary" onclick="go('student-task-detail')">\u7ee7\u7eed\u5f53\u524d\u5b9e\u9a8c ${icon('arrow-right')}</button></div></div><div class="course-learning-shell"><aside class="panel course-chapter-nav"><div class="panel-title"><h2>\u8bfe\u7a0b\u7ae0\u8282</h2><span class="status good">\u8fdb\u884c\u4e2d</span></div>${['1. \u7f51\u7edc\u57fa\u7840','2. DNS \u6545\u969c\u5b9a\u4f4d','3. \u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5','4. \u4fee\u590d\u5e76\u9a8c\u8bc1','5. \u5b9e\u9a8c\u603b\u7ed3'].map((chapter,index)=>`<button class="course-chapter-row ${index===2?'active':''}" onclick="${index===2?'openStudentTaskDetail(\'task-linux-network\')':'toast(\'该章节内容（演示）\')'}"><span>${index<2?'✓':index+1}</span><strong>${chapter}</strong><small>${index<2?'已完成':index===2?'进行中':'未开始'}</small></button>`).join('')}</aside><section class="course-learning-main"><section class="panel"><div class="panel-title"><h2>\u672c\u5468\u5b66\u4e60\u8def\u5f84</h2><span class="subtle">3 / 5 \u4e2a\u5b9e\u9a8c</span></div><div class="progress large"><span style="width:68%"></span></div><div class="course-learning-stats"><span><strong>68%</strong> \u5f53\u524d\u8fdb\u5ea6</span><span><strong>2</strong> \u4e2a\u5f85\u5b8c\u6210\u9636\u6bb5</span><span><strong>10\u670813\u65e5</strong> \u6700\u8fd1\u622a\u6b62</span></div></section><div class="grid two"><section class="panel"><div class="panel-title"><h2>\u8bfe\u7a0b\u8d44\u6599</h2><span class="subtle">4 \u9879</span></div><div class="item"><div><strong>\u5b9e\u9a8c\u624b\u518c.pdf</strong><small>\u8bfe\u7a0b\u6750\u6599 · \u5df2\u9605\u8bfb</small></div><button class="btn sm" onclick="toast('材料预览（演示）')">\u9884\u89c8</button></div><div class="item"><div><strong>\u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5\u6e05\u5355</strong><small>\u7b2c 3 \u7ae0 · \u5efa\u8bae\u5148\u9605\u8bfb</small></div><button class="btn sm" onclick="openStudentTaskDetail()">\u6253\u5f00</button></div></section><section class="panel"><div class="panel-title"><h2>\u8fd1\u671f\u6d3b\u52a8</h2><span class="subtle">\u8bfe\u7a0b\u516c\u544a</span></div><div class="item"><div><strong>\u7b2c 3 \u9636\u6bb5\u5b9e\u9a8c\u62a5\u544a\u8981\u6c42\u5df2\u66f4\u65b0</strong><small>\u5468\u8001\u5e08 · \u4eca\u5929 08:45</small></div><button class="btn sm" onclick="openStudentTaskDetail()">\u67e5\u770b</button></div><div class="item"><div><strong>\u672c\u5468\u5b9e\u9a8c\u65e5\u5386</strong><small>\u6700\u8fd1\u622a\u6b62：10 \u6708 13 \u65e5 18:00</small></div><button class="btn sm" onclick="go('student-home')">\u6253\u5f00\u65e5\u5386</button></div></section></div></section></div>`;
  lucide.createIcons();
}
function readStudentStoredJson(key,fallback){try{return JSON.parse(localStorage.getItem(key))||fallback}catch{return fallback}}
function studentReportChapter(taskId=selectedStudentTaskId){return taskId==='task-linux-network'?'routing':String(taskId||'').replace(/^task-/,'')}
function openStudentReportRecord(kind){
  const chapter=studentReportChapter();
  const versions=readStudentStoredJson('edu-agent-report-versions',[]).filter(item=>item.chapter===chapter);
  const submission=readStudentStoredJson('edu-agent-report-submission',null)?.chapter===chapter?readStudentStoredJson('edu-agent-report-submission',null):null;
  const review=chapter==='routing'?readStudentStoredJson('edu-agent-student-review-result',null):null;
  let modal=$('#studentReportRecordModal');
  if(!modal){
    $('#modalRoot').insertAdjacentHTML('beforeend','<div class="modal-backdrop" id="studentReportRecordModal" onclick="backdrop(event,\'studentReportRecordModal\')"><div class="modal"><div id="studentReportRecordModalContent"></div></div></div>');
    modal=$('#studentReportRecordModal');
  }
  const content=$('#studentReportRecordModalContent');
  if(!content)return;
  if(kind==='versions'){
    const rows=versions;
    content.innerHTML=`<div class="modal-eyebrow">报告记录</div><h2>报告版本</h2><div class="history-list">${rows.length?rows.map(item=>`<div class="history-row"><div><strong>${escapeCalendarHtml(item.label)}</strong><small>${escapeCalendarHtml(item.time)} · ${escapeCalendarHtml(item.status)}</small></div><span class="status neutral">${escapeCalendarHtml(item.chapter||'当前阶段')}</span></div>`).join(''):'<p class="subtle">当前还没有保存的报告版本。</p>'}</div><div class="modal-actions"><button class="btn" onclick="closeModal('studentReportRecordModal')">关闭</button></div>`;
  }else{
    const status=review?.status==='RETURNED'?'报告已退回修改':review?.status==='APPROVED'?`评审完成 · ${review.score||0} 分`:submission?'报告已提交，等待教师评审':'暂无评审结果';
    const feedback=review?.feedback||'教师尚未添加文字批注。';
    content.innerHTML=`<div class="modal-eyebrow">报告记录</div><h2>评审意见</h2><div class="status-line ${review?.status==='RETURNED'?'is-blocked':'is-ok'}">${escapeCalendarHtml(status)}</div><p class="subtle">${escapeCalendarHtml(feedback)}</p><div class="modal-actions"><button class="btn" onclick="closeModal('studentReportRecordModal')">关闭</button></div>`;
  }
  openModal('studentReportRecordModal');
}
function renderStudentReportRecords(task){
  const chapter=studentReportChapter(task?.id);
  const versions=readStudentStoredJson('edu-agent-report-versions',[]).filter(item=>item.chapter===chapter);
  const storedSubmission=readStudentStoredJson('edu-agent-report-submission',null);
  const submission=storedSubmission?.chapter===chapter?storedSubmission:null;
  const review=chapter==='routing'?readStudentStoredJson('edu-agent-student-review-result',null):null;
  const status=review?.status==='RETURNED'?'需修改':review?.status==='APPROVED'?'已评审':submission?'待评审':'草稿';
  const statusStyle=review?.status==='RETURNED'?'warn':review?.status==='APPROVED'?'good':'neutral';
  const savedAt=submission?.submittedAt||versions[0]?.time||'暂无记录';
  const score=review?.score?`${review.score} 分`:'暂无评分';
  return `<section class="panel student-report-records"><div class="panel-title"><h2>报告记录</h2><span class="status ${statusStyle}">${status}</span></div><div class="report-record-grid"><div><span class="eyebrow">最近保存</span><strong>${escapeCalendarHtml(savedAt)}</strong></div><div><span class="eyebrow">评分</span><strong>${escapeCalendarHtml(score)}</strong></div></div><div class="form-actions"><button class="btn sm" onclick="openStudentReportRecord('versions')">报告版本</button><button class="btn sm" onclick="openStudentReportRecord('review')">评审意见</button></div></section>`;
}
function renderStudentTaskDetail(){
  const target=$('#student-task-detail');
  const task=studentCalendarTasks.find(item=>item.id===selectedStudentTaskId)||studentCalendarTasks[0];
  if(!target||!task)return;
  const deadline=calendarDateKey(task.effective_deadline);
  target.innerHTML=`<div class="crumb">\u5b66\u751f\u95e8\u6237　/　\u5b9e\u9a8c\u4efb\u52a1　/　${escapeCalendarHtml(task.title)}</div><div class="head"><div><h1>${escapeCalendarHtml(task.title)}</h1><p>${escapeCalendarHtml(task.course)} · \u4efb\u52a1\u8be6\u60c5\u4e0e\u5b8c\u6210\u8def\u5f84</p></div><div class="actions"><button class="btn" onclick="go('student-tasks')">\u8fd4\u56de\u4efb\u52a1</button>${task.id==='task-linux-network'?'<button class="btn primary" onclick="openWorkbench()">进入实验工作台 '+icon('arrow-right')+'</button>':''}</div></div><div class="metric-group">${metric('\u4efb\u52a1\u72b6\u6001',calendarTaskStatusLabel(task.status),deadline?'\u622a\u6b62 '+calendarDateLabel(deadline):'\u6682\u65e0\u622a\u6b62','circle-check')}${metric('\u5f53\u524d\u5b8c\u6210\u5ea6',`${task.progress}%`,'\u6bcf\u9636\u6bb5\u5b8c\u6210\u540e\u63d0\u4ea4\u62a5\u544a','chart-no-axes-combined')}${metric('\u5df2\u5b8c\u6210\u9636\u6bb5','2 / 5','\u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5\u8fdb\u884c\u4e2d','list-checks')}${metric('\u5141\u8bb8\u64cd\u4f5c','3','\u4ee5\u5f53\u524d\u4efb\u52a1\u72b6\u6001\u4e3a\u51c6','shield-check')}</div><div class="grid two section"><section class="panel"><div class="panel-title"><h2>\u5b8c\u6210\u8def\u5f84</h2><span class="subtle">\u6309\u5e8f\u5b8c\u6210</span></div><div class="workflow-list"><div class="workflow-step complete"><span>✓</span><div><strong>\u5b9e\u9a8c\u51c6\u5907</strong><small>\u73af\u5883\u4e0e\u4f9d\u8d56\u68c0\u67e5\u5df2\u5b8c\u6210</small></div></div><div class="workflow-step complete"><span>✓</span><div><strong>DNS \u6545\u969c\u5b9a\u4f4d</strong><small>\u5df2\u901a\u8fc7\u6d4b\u8bd5\u5e76\u4fdd\u5b58\u68c0\u70b9</small></div></div><div class="workflow-step current"><span>3</span><div><strong>\u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5</strong><small>\u9700\u8fdb\u5165\u5de5\u4f5c\u53f0\u5b8c\u6210\u6d4b\u8bd5\u548c\u62a5\u544a</small></div></div><div class="workflow-step"><span>4</span><div><strong>\u4fee\u590d\u5e76\u9a8c\u8bc1</strong><small>\u524d\u4e00\u9636\u6bb5\u62a5\u544a\u63d0\u4ea4\u540e\u89e3\u9501</small></div></div></div></section><section class="panel"><div class="panel-title"><h2>\u4efb\u52a1\u8981\u6c42</h2><span class="status good">\u53ef\u5f00\u59cb</span></div><p class="detail-copy">\u786e\u8ba4\u9ed8\u8ba4\u8def\u7531\u914d\u7f6e\uff0c\u68c0\u67e5\u76ee\u6807\u670d\u52a1\u7aef\u53e3\u662f\u5426\u53ef\u8fbe\uff0c\u5e76\u5728\u62a5\u544a\u4e2d\u8bf4\u660e\u5bfc\u81f4\u6545\u969c\u7684\u539f\u56e0\u3002</p><div class="status-line">✓　\u5de5\u4f5c\u533a\u5feb\u7167\u4fdd\u5b58\u540e\u624d\u80fd\u63d0\u4ea4\u62a5\u544a</div><div class="status-line">✓　\u5fc5\u8981\u6d4b\u8bd5\u7528\u4f8b\u9700\u5168\u90e8\u901a\u8fc7</div><div class="status-line">✓　\u6559\u5e08\u53ef\u5728\u63d0\u4ea4\u540e\u8fdb\u884c\u8bc4\u5ba1</div><div class="form-actions"><button class="btn" onclick="go('student-notifications')">\u67e5\u770b\u76f8\u5173\u901a\u77e5</button><button class="btn" onclick="toast('延期申请（演示）')">\u7533\u8bf7\u5ef6\u671f</button></div></section></div>`;
   target.insertAdjacentHTML('beforeend',renderStudentReportRecords(task));
   lucide.createIcons();
}
function renderStudentNotifications(){
  const target=$('#student-notifications');
  if(!target)return;
  const unread=studentNotifications.filter(item=>!item.read).length;
  target.innerHTML=`<div class="crumb">\u5b66\u751f\u95e8\u6237　/　\u901a\u77e5</div><div class="head"><div><h1>\u901a\u77e5\u4e0e\u5b66\u4e60\u652f\u6301</h1><p>\u622a\u6b62\u63d0\u9192\u3001\u62a5\u544a\u8bc4\u5ba1\u548c\u5e73\u53f0\u6d88\u606f\u96c6\u4e2d\u5728\u8fd9\u91cc\u5904\u7406\u3002</p></div><div class="actions"><span class="status ${unread?'warn':'good'}">${unread?`${unread} \u6761\u672a\u8bfb`:'\u5168\u90e8\u5df2\u8bfb'}</span><button class="btn" onclick="toast('已全部标记为已读')">\u5168\u90e8\u5df2\u8bfb</button></div></div><div class="notification-list">${studentNotifications.map(item=>`<article class="notification-card ${item.read?'read':''}"><div class="notification-icon"><i data-lucide="${item.type==='deadline'?'calendar-clock':item.type==='review'?'message-square-more':'bell'}"></i></div><div class="notification-copy"><div class="notification-card-head"><strong>${item.title}</strong><small>${item.time}</small></div><p>${item.body}</p><div class="notification-actions"><button class="btn sm" onclick="go('${item.action}')">${item.action==='student-task-detail'?'查看任务':'打开相关页面'}</button>${item.read?'':'<button class="btn sm" onclick="markStudentNotificationRead(\''+item.id+'\')">标记已读</button>'}</div></div></article>`).join('')}</div><section class="panel section"><div class="panel-title"><h2>\u5b66\u4e60\u5efa\u8bae</h2><span class="status blue">\u57fa\u4e8e\u8fdb\u5ea6</span></div><div class="recommendation-grid"><div class="recommendation"><strong>\u5148\u5b8c\u6210\u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5</strong><small>\u4f60\u7684\u4e0b\u4e00\u4e2a\u622a\u6b62\u4efb\u52a1\uff0c\u5269\u4f59 1 \u5929。</small><button class="btn sm primary" onclick="openStudentTaskDetail()">\u7ee7\u7eed\u5b9e\u9a8c</button></div><div class="recommendation"><strong>\u590d\u4e60 DNS \u6545\u969c\u5b9a\u4f4d</strong><small>\u5df2\u5b8c\u6210\u7684\u7ae0\u8282\u53ef\u4f5c\u4e3a\u5f53\u524d\u9636\u6bb5\u7684\u53c2\u8003\u3002</small><button class="btn sm" onclick="openStudentCourseDetail()">\u67e5\u770b\u7ae0\u8282</button></div></div></section>`;
  lucide.createIcons();
}
function renderTeacherExpandedScreens(){
  const enrollments=$('#teacher-enrollments');
  if(enrollments)enrollments.innerHTML=`<div class="crumb">\u6559\u5e08\u95e8\u6237　/　\u9009\u8bfe\u7ba1\u7406</div><div class="head"><div><h1>\u9009\u8bfe\u7ba1\u7406</h1><p>\u5ba1\u6838\u5b66\u751f\u7533\u8bf7\uff0c\u7ef4\u62a4\u8bfe\u7a0b\u6210\u5458\u4e0e\u9080\u8bf7\u7801\u3002</p></div><div class="actions"><button class="btn" onclick="toast('批量导入预检（演示）')">\u6279\u91cf\u5bfc\u5165</button><button class="btn primary" onclick="toast('邀请码已复制（演示）')">\u590d\u5236\u9080\u8bf7\u7801 ${icon('copy')}</button></div></div><div class="metric-group">${metric('\u5f85\u5ba1\u6838',String(teacherEnrollmentRows.filter(row=>row.status==='PENDING').length),'\u9700\u4f60\u5904\u7406','user-round-check')}${metric('\u5df2\u901a\u8fc7',String(teacherEnrollmentRows.filter(row=>row.status==='APPROVED').length),'\u5f53\u524d\u5b66\u671f','users-round')}${metric('\u672c\u6708\u7533\u8bf7','18','\u8f83\u4e0a\u6708 + 12%','trending-up')}${metric('\u8bfe\u7a0b\u5bb9\u91cf','96 / 120','\u5269\u4f59 24 \u4e2a\u540d\u989d','gauge')}</div><section class="panel section"><div class="panel-title"><h2>\u7533\u8bf7\u5217\u8868</h2><div class="actions"><button class="btn sm">\u5f85\u5ba1\u6838</button><button class="btn sm">\u5168\u90e8\u8bfe\u7a0b ${icon('chevron-down')}</button></div></div><div class="table-wrap"><table class="table"><thead><tr><th>\u5b66\u751f</th><th>\u8bfe\u7a0b</th><th>\u7533\u8bf7\u8bf4\u660e</th><th>\u7533\u8bf7\u65f6\u95f4</th><th>\u72b6\u6001</th><th>\u64cd\u4f5c</th></tr></thead><tbody>${teacherEnrollmentRows.map(row=>`<tr><td><strong>${row.student}</strong></td><td>${row.course}</td><td data-wrap>${row.message}</td><td>${row.time}</td><td><span class="status ${row.status==='PENDING'?'warn':row.status==='APPROVED'?'good':'neutral'}">${row.status==='PENDING'?'待审核':row.status==='APPROVED'?'已通过':'已拒绝'}</span></td><td>${row.status==='PENDING'?`<button class="btn sm" onclick="reviewTeacherEnrollment('${row.id}','approve')">通过</button><button class="btn sm" onclick="reviewTeacherEnrollment('${row.id}','reject')">拒绝</button>`:'<button class="btn sm" onclick="toast(\'查看申请详情（演示）\')">查看</button>'}</td></tr>`).join('')}</tbody></table></div></section><section class="grid two section"><div class="panel"><div class="panel-title"><h2>\u9080\u8bf7\u7801</h2><span class="status good">\u5df2\u542f\u7528</span></div><div class="invite-code">NET-2026-A1B7</div><p class="subtle">\u4ec5\u53ef\u7528\u4e8e\u8ba1\u7b97\u673a\u7f51\u7edc\u8bfe\u7a0b\uff0c\u4e8e 10 \u6708 20 \u65e5\u5931\u6548\u3002</p></div><div class="panel"><div class="panel-title"><h2>\u6279\u91cf\u5bfc\u5165\u4f5c\u4e1a</h2><span class="status neutral">\u65e0\u8fdb\u884c\u4e2d\u4f5c\u4e1a</span></div><p class="subtle">\u5148\u9884\u68c0 CSV \u4e2d\u7684\u5b66\u53f7\u3001\u90ae\u7bb1\u548c\u8bfe\u7a0b\u5206\u7ec4\uff0c\u518d\u6267\u884c\u5bfc\u5165\u3002</p><button class="btn sm" onclick="toast('上传导入文件（演示）')">\u9009\u62e9\u6587\u4ef6</button></div></section>`;
  const publishing=$('#teacher-publishing');
  if(publishing)publishing.innerHTML=`<div class="crumb">\u6559\u5e08\u95e8\u6237　/　\u5b9e\u9a8c\u53d1\u5e03</div><div class="head"><div><h1>\u5b9e\u9a8c\u53d1\u5e03</h1><p>\u4ece\u6a21\u677f\u9884\u68c0\u5230\u5f00\u653e\u65f6\u95f4\uff0c\u7edf\u4e00\u7ba1\u7406\u5b9e\u9a8c\u751f\u547d\u5468\u671f\u3002</p></div><button class="btn primary" onclick="go('template-editor')">\u914d\u7f6e\u65b0\u53d1\u5e03 ${icon('plus')}</button></div><section class="panel section"><div class="table-wrap"><table class="table"><thead><tr><th>\u5b9e\u9a8c\u53d1\u5e03</th><th>\u7248\u672c</th><th>\u5bf9\u8c61\u73ed\u7ea7</th><th>\u65f6\u95f4\u7a97\u53e3</th><th>\u4efb\u52a1\u6570</th><th>\u72b6\u6001</th><th>\u64cd\u4f5c</th></tr></thead><tbody>${teacherPublicationRows.map(row=>`<tr><td><strong>${row.name}</strong></td><td>${row.version}</td><td>${row.audience}</td><td data-wrap>${row.window}</td><td>${row.tasks}</td><td><span class="status ${row.status==='PUBLISHED'?'good':row.status==='PRECHECK'?'warn':row.status==='WITHDRAWN'?'neutral':'blue'}">${row.status==='PUBLISHED'?'已发布':row.status==='PRECHECK'?'待预检':row.status==='WITHDRAWN'?'已撤回':'草稿'}</span></td><td>${row.status==='DRAFT'?`<button class="btn sm" onclick="publishTeacherExperiment('${row.id}','precheck')">运行预检</button>`:row.status==='PRECHECK'?`<button class="btn sm primary" onclick="publishTeacherExperiment('${row.id}','publish')">发布</button>`:row.status==='PUBLISHED'?`<button class="btn sm" onclick="publishTeacherExperiment('${row.id}','withdraw')">撤回</button>`:'<button class="btn sm" onclick="publishTeacherExperiment(\''+row.id+'\',\'precheck\')">重新检查</button>'}</td></tr>`).join('')}</tbody></table></div></section><section class="grid three section"><div class="panel"><div class="panel-title"><h2>\u9884\u68c0\u72b6\u6001</h2><span class="status good">2 / 3 \u901a\u8fc7</span></div><div class="status-line">✓　\u57fa\u7840\u4fe1\u606f\u5b8c\u6574</div><div class="status-line">✓　\u955c\u50cf\u6cbb\u7406\u72b6\u6001\u6709\u6548</div><div class="status-line" style="color:var(--amber)">!　\u7b2c 3 \u7ae0\u8d44\u6e90\u89c4\u683c\u5f85\u66f4\u65b0</div></div><div class="panel"><div class="panel-title"><h2>\u4efb\u52a1\u5bf9\u8d26</h2><span class="status blue">186 \u4e2a\u4efb\u52a1</span></div><p class="subtle">\u53d1\u5e03\u540e\u7cfb\u7edf\u4f1a\u6309\u5b66\u751f\u548c\u7ae0\u8282\u751f\u6210\u4efb\u52a1\u3002</p></div><div class="panel"><div class="panel-title"><h2>\u53d1\u5e03\u7a97\u53e3</h2><span class="status good">\u6b63\u5e38</span></div><p class="subtle">\u5f53\u524d\u5b66\u671f\u652f\u6301\u6309\u73ed\u7ea7\u3001\u5b66\u751f\u7ec4\u9009\u62e9\u3002</p></div></section>`;
  const progress=$('#teacher-progress');
  if(progress)progress.innerHTML=`<div class="crumb">\u6559\u5e08\u95e8\u6237　/　\u5b66\u751f\u8fc7\u7a0b</div><div class="head"><div><h1>\u5b66\u751f\u8fc7\u7a0b</h1><p>\u4ece\u8fdb\u5ea6\u3001\u5de5\u4f5c\u533a\u4f1a\u8bdd\u548c\u62a5\u544a\u63d0\u4ea4\u60c5\u51b5\u5b9a\u4f4d\u9700\u8981\u5173\u6ce8\u7684\u5b66\u751f\u3002</p></div><div class="actions"><button class="btn">\u5168\u90e8\u8bfe\u7a0b ${icon('chevron-down')}</button><button class="btn primary" onclick="go('teacher-reviews')">\u8fdb\u5165\u8bc4\u5ba1</button></div></div><div class="metric-group">${metric('\u6b63\u5e38\u8fdb\u884c','76','\u4eba','users-round')}${metric('\u957f\u65f6\u672a\u6d3b\u8dc3','8','\u8d85\u8fc7 7 \u5929','clock-3')}${metric('\u62a5\u544a\u5f85\u5ba1','28','\u4efd','file-check-2')}${metric('\u5b9e\u9a8c\u5931\u8d25','3','\u4e2a\u4efb\u52a1','triangle-alert')}</div><section class="panel section"><div class="panel-title"><h2>\u5b66\u751f\u8fdb\u5ea6\u4e0e\u98ce\u9669</h2><input class="field" style="max-width:220px" placeholder="\u641c\u7d22\u5b66\u751f" oninput="filterTable(this,'teacherProgressTable')"></div><div class="table-wrap"><table class="table" id="teacherProgressTable"><thead><tr><th>\u5b66\u751f</th><th>\u5f53\u524d\u4efb\u52a1</th><th>\u8fdb\u5ea6</th><th>\u6700\u8fd1\u6d3b\u52a8</th><th>\u5de5\u4f5c\u533a</th><th>\u62a5\u544a</th><th>\u98ce\u9669</th></tr></thead><tbody>${[['\u6797\u77e5\u590f','\u8def\u7531\u4e0e\u7aef\u53e3\u68c0\u67e5','68%','今天 14:26','在线','草稿','正常'],['\u9648\u5b50\u8c6a','DNS \u6545\u969c\u5b9a\u4f4d','42%','3 天前','已过期','未提交','需要关注'],['\u8d75\u4e91\u5e06','\u5b9e\u9a8c\u51c6\u5907','12%','今天 09:18','准备中','未开始','正常']].map(row=>`<tr><td><strong>${row[0]}</strong></td><td>${row[1]}</td><td><div class="progress"><span style="width:${row[2]}"></span></div><small>${row[2]}</small></td><td>${row[3]}</td><td><span class="status ${row[4]==='在线'?'good':row[4]==='已过期'?'warn':'neutral'}">${row[4]}</span></td><td>${row[5]}</td><td><span class="status ${row[6]==='需要关注'?'warn':'good'}">${row[6]}</span></td></tr>`).join('')}</tbody></table></div></section>`;
  lucide.createIcons();
}
function renderAdminExpandedScreens(){
  const resources=$('#admin-resources');
  if(resources)resources.innerHTML=`<div class="crumb">\u5e73\u53f0\u7ba1\u7406　/　\u8d44\u6e90\u6cbb\u7406</div><div class="head"><div><h1>\u8d44\u6e90\u6cbb\u7406</h1><p>\u7edf\u4e00\u67e5\u770b\u955c\u50cf\u3001\u8fd0\u884c\u65f6\u3001\u914d\u989d\u548c\u5b9e\u4f8b\u8d44\u6e90\u3002</p></div><div class="actions"><button class="btn" onclick="go('admin-governance')">\u67e5\u770b\u6cbb\u7406\u544a\u8b66</button><button class="btn primary" onclick="toast('资源巡检已启动（演示）')">\u542f\u52a8\u5de1\u68c0</button></div></div><div class="metric-group">${metric('\u8fd0\u884c\u4e2d\u5b9e\u4f8b','62','\u5f53\u524d\u5360\u7528 71%','server')}${metric('\u5df2\u6cbb\u7406\u955c\u50cf','18','\u5168\u90e8\u901a\u8fc7\u626b\u63cf','container')}${metric('\u914d\u989d\u9884\u8b66','4','\u9700\u8981\u5173\u6ce8','gauge')}${metric('\u5de5\u4f5c\u533a\u4f1a\u8bdd','84','\u6d3b\u8dc3\u4e2d','monitor-dot')}</div><div class="grid two section"><section class="panel"><div class="panel-title"><h2>\u8fd0\u884c\u65f6\u5065\u5eb7</h2><span class="status good">\u5168\u90e8\u6b63\u5e38</span></div><div class="resource-health-row"><span>Docker Sandbox · v3</span><span class="status good">\u5065\u5eb7 99.8%</span></div><div class="resource-health-row"><span>Notebook Runtime · v2</span><span class="status good">\u5065\u5eb7 99.4%</span></div><div class="resource-health-row"><span>Judge Worker · v1</span><span class="status warn">\u5bb9\u91cf 72%</span></div></section><section class="panel"><div class="panel-title"><h2>\u914d\u989d\u4e0e\u5b58\u50a8</h2><span class="subtle">\u5f53\u524d\u5b66\u671f</span></div><div class="quota-line"><span>CPU</span><div class="progress"><span style="width:71%"></span></div><strong>71%</strong></div><div class="quota-line"><span>\u5185\u5b58</span><div class="progress"><span style="width:58%"></span></div><strong>58%</strong></div><div class="quota-line"><span>\u5bf9\u8c61\u5b58\u50a8</span><div class="progress"><span style="width:43%"></span></div><strong>43%</strong></div></section></div><section class="panel section"><div class="panel-title"><h2>\u955c\u50cf\u4e0e\u8d44\u6e90\u5e93</h2><span class="subtle">\u53ea\u8bfb\u6c47\u603b</span></div><div class="table-wrap"><table class="table"><thead><tr><th>\u8d44\u6e90</th><th>\u7248\u672c</th><th>\u72b6\u6001</th><th>\u6700\u8fd1\u68c0\u67e5</th><th>\u4f7f\u7528\u91cf</th></tr></thead><tbody>${tableRows([['Ubuntu Network Lab','v2.4 · sha256:8f2c…b91','<span class="status good">已批准</span>','今天 14:22','32 个实例'],['Docker Sandbox','v3 · adapter-03','<span class="status good">在线</span>','今天 14:20','84 个会话'],['medium · 2 vCPU · 4 GB','resource-profile-02','<span class="status warn">接近配额</span>','今天 14:18','78%']])}</tbody></table></div></section>`;
  const incidents=$('#admin-incidents');
  if(incidents)incidents.innerHTML=`<div class="crumb">\u5e73\u53f0\u7ba1\u7406　/　\u5f02\u5e38\u4e2d\u5fc3</div><div class="head"><div><h1>\u5f02\u5e38\u4e2d\u5fc3</h1><p>\u96c6\u4e2d\u5904\u7406\u5b9e\u9a8c\u4efb\u52a1\u3001\u62a5\u544a\u626b\u63cf\u3001\u6a21\u677f\u9884\u68c0\u4e0e\u8fd0\u884c\u8865\u507f\u3002</p></div><div class="actions"><button class="btn">\u8fd1 7 \u5929 ${icon('chevron-down')}</button><button class="btn primary" onclick="toast('异常导出已开始（演示）')">\u5bfc\u51fa\u5904\u7406\u6e05\u5355</button></div></div><div class="metric-group">${metric('\u5f85\u5904\u7406','7','\u8de8\u4efb\u52a1\u4e0e\u8d44\u6e90','triangle-alert')}${metric('\u9ad8\u4f18\u5148\u7ea7','2','\u9700\u8981\u5feb\u901f\u54cd\u5e94','siren')}${metric('\u5f85\u8865\u507f','3','\u5931\u8d25\u4f5c\u4e1a','rotate-ccw')}${metric('\u4eca\u65e5\u5df2\u89e3\u51b3','14','\u8fd1 24 \u5c0f\u65f6','circle-check')}</div><section class="panel section"><div class="panel-title"><h2>\u5f02\u5e38\u961f\u5217</h2><input class="field" style="max-width:230px" placeholder="\u641c\u7d22\u4efb\u52a1、Trace 或\u8d44\u6e90" oninput="filterTable(this,'adminIncidentTable')"></div><div class="table-wrap"><table class="table" id="adminIncidentTable"><thead><tr><th>\u7c7b\u578b</th><th>\u5bf9\u8c61</th><th>\u7ea7\u522b</th><th>\u53d1\u751f\u65f6\u95f4</th><th>\u8d1f\u8d23\u4eba</th><th>\u5904\u7406</th></tr></thead><tbody>${tableRows([['\u5b9e\u9a8c\u4efb\u52a1\u5f02\u5e38','task_01M4…','<span class="status warn">中</span>','今天 10:02','\u5f85\u5206\u6d3e','<button class="btn sm" onclick="toast(\'已打开异常详情（演示）\')">查看详情</button>'],['\u62a5\u544a\u626b\u63cf','report_01M4…','<span class="status neutral">低</span>','今天 09:14','\u5b89\u5168\u7ec4','<button class="btn sm" onclick="toast(\'已标记为复核（演示）\')">复核</button>'],['\u6a21\u677f\u9884\u68c0','template-v1.4','<span class="status warn">中</span>','昨天 18:40','\u5468\u8001\u5e08','<button class="btn sm" onclick="go(\'teacher-publishing\')">查看发布</button>']])}</tbody></table></div></section><section class="grid two section"><div class="panel"><div class="panel-title"><h2>\u8865\u507f\u4f5c\u4e1a</h2><span class="status warn">3 \u4e2a\u5f85\u8fd0\u884c</span></div><p class="subtle">\u5f02\u5e38\u5b9e\u4f8b\u56de\u6536\u3001\u6587\u4ef6\u626b\u63cf\u5931\u8d25\u548c\u4efb\u52a1\u91cd\u8bd5\u5747\u4f1a\u8fdb\u5165\u8865\u507f\u961f\u5217\u3002</p><button class="btn sm" onclick="go('admin-audit')">\u67e5\u770b\u64cd\u4f5c\u65e5\u5fd7</button></div><div class="panel"><div class="panel-title"><h2>\u5b89\u5168\u4e0e\u5ba1\u8ba1</h2><span class="status good">\u65e0\u9ad8\u98ce\u9669</span></div><p class="subtle">\u5f53\u524d\u6ca1\u6709\u9700\u8981\u5347\u7ea7\u7684\u5b89\u5168\u544a\u8b66\u3002</p><button class="btn sm" onclick="go('admin-audit')">\u67e5\u770b\u5ba1\u8ba1</button></div></section>`;
  lucide.createIcons();
}
function renderExpandedScreens(){
  renderStudentCourseDetail();
  renderStudentTaskDetail();
  renderStudentNotifications();
  renderTeacherExpandedScreens();
  renderAdminExpandedScreens();
  document.querySelectorAll('#student-courses tbody tr button').forEach(button=>button.setAttribute('onclick',"openStudentCourseDetail()"));
}

function renderSettings(){ $('#settings').innerHTML=html`<div class="crumb">${portalConfig[currentPortal].label}　/　个人设置</div><div class="head"><div><h1>个人设置</h1><p>管理个人资料、通知偏好和登录安全。</p></div></div><div class="grid two"><section class="panel"><div class="panel-title"><h2>个人资料</h2><span class="status neutral">演示数据</span></div><div class="drawer-profile" style="padding-top:8px"><span class="avatar large">${portalConfig[currentPortal].avatar}</span><div><strong>${portalConfig[currentPortal].name}</strong><p>${portalConfig[currentPortal].role}</p></div></div><label class="form-label">显示名称</label><input class="field" value="${portalConfig[currentPortal].name}"><label class="form-label">邮箱</label><input class="field" value="lin.zhixia@example.edu"><button class="btn primary" style="margin-top:15px" onclick="toast('个人资料已保存（演示）')">保存修改</button></section><section class="panel"><div class="panel-title"><h2>通知偏好</h2></div><div class="item"><div><strong>实验截止提醒</strong><small>在截止前 24 小时提醒我</small></div><span class="status good">已开启</span></div><div class="item"><div><strong>报告评审结果</strong><small>教师完成评审后通知我</small></div><span class="status good">已开启</span></div><div class="item"><div><strong>平台公告</strong><small>接收平台维护和服务通知</small></div><span class="status neutral">已关闭</span></div></section></div>` }

function chart(id,type,labels,datasets){const canvas=document.getElementById(id);if(!canvas||typeof Chart==='undefined')return;charts[id]?.destroy();charts[id]=new Chart(canvas,{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#26363b',padding:8}},scales:type==='doughnut'?{}:{x:{grid:{display:false},ticks:{font:{size:9},color:'#899496'},border:{display:false}},y:{grid:{color:'#eef1ef'},ticks:{font:{size:9},color:'#899496'},border:{display:false},beginAtZero:true}}}})}
function initCharts(){chart('studentTrend','line',['一','二','三','四','五','六','日'],[{data:[25,38,20,45,52,35,60],borderColor:'#2f7069',backgroundColor:'#e7f0ed',fill:true,tension:.28,borderWidth:2,pointRadius:2,pointBackgroundColor:'#2f7069'}]);chart('teacherTrend','line',['10/04','10/05','10/06','10/07','10/08','10/09','10/10'],[{data:[48,55,53,65,69,74,76],borderColor:'#2f7069',backgroundColor:'#e7f0ed',fill:true,tension:.28,borderWidth:2,pointRadius:2,pointBackgroundColor:'#2f7069'}]);chart('analyticsTrend','line',['第 1 周','第 2 周','第 3 周','第 4 周','第 5 周'],[{data:[58,63,69,72,76],borderColor:'#2f7069',backgroundColor:'#e7f0ed',fill:true,tension:.28,borderWidth:2,pointRadius:2,pointBackgroundColor:'#2f7069'}]);chart('resourceTrend','line',['00','04','08','12','16','20','24'],[{data:[42,44,48,52,62,58,62],borderColor:'#2f7069',tension:.28,borderWidth:2,pointRadius:2,pointBackgroundColor:'#2f7069'},{data:[58,60,61,65,70,69,71],borderColor:'#9b7d54',tension:.28,borderWidth:2,pointRadius:2,pointBackgroundColor:'#9b7d54'}]);chart('incidentTrend','bar',['10/04','10/05','10/06','10/07','10/08','10/09','10/10'],[{data:[2,1,4,2,1,3,1],backgroundColor:'#d9a66b',borderWidth:0,barPercentage:.52}])}
function resizeCharts(){Object.values(charts).forEach(instance=>instance.resize())}
function renderModals(){
  $('#modalRoot').innerHTML=html`<div class="modal-backdrop" id="create" onclick="backdrop(event,'create')"><div class="modal"><h2>新建实验模板</h2><p>模板属于当前课程。创建后会建立草稿版本，运行环境、章节任务和评分配置可逐步完善。</p><label class="form-label">模板名称 *</label><input class="field" id="templateName" placeholder="例如：Linux 网络故障排查实验"><label class="form-label">实验分类</label><select class="field"><option>网络基础</option><option>操作系统</option><option>数据库</option></select><label class="form-label">模板简介</label><textarea class="field" rows="3" placeholder="简要描述实验目标与适用场景"></textarea><div class="modal-actions"><button class="btn" onclick="closeModal('create')">取消</button><button class="btn primary" onclick="createTemplate()">创建并进入配置</button></div></div></div><div class="modal-backdrop" id="precheck" onclick="backdrop(event,'precheck')"><div class="modal"><h2>运行模板预检</h2><p>系统将校验镜像治理状态、运行时健康、资源规格、执行配置及章节任务。</p><div class="status-line">✓　镜像已通过治理扫描</div><div class="status-line">✓　运行时适配器健康</div><div class="status-line" style="color:var(--amber)">!　第 3 章资源规格需更新</div><div class="modal-actions"><button class="btn" onclick="closeModal('precheck')">取消</button><button class="btn primary" onclick="closeModal('precheck');toast('预检完成：发现 1 个资源阻塞项')">开始预检</button></div></div></div><div class="modal-backdrop" id="images" onclick="backdrop(event,'images')"><div class="modal"><h2>选择已治理镜像</h2><p>只展示已准备且通过治理的镜像。发布时会固定 digest。</p><div class="item"><div><strong>Ubuntu Network Lab · v2.4</strong><small>sha256:8f2c…b91 · 扫描通过 · 已批准</small></div><button class="btn sm primary" onclick="closeModal('images');selectResource(document.querySelector('.resource'), 'Ubuntu Network Lab · v2.4')">选择</button></div><div class="item"><div><strong>Ubuntu Network Lab · v2.3</strong><small>sha256:10ae…f31 · 扫描通过 · 已批准</small></div><button class="btn sm" onclick="closeModal('images');toast('已选择 Ubuntu Network Lab v2.3')">选择</button></div><div class="modal-actions"><button class="btn" onclick="toast('课程镜像准备流程（演示）')">准备课程镜像</button><button class="btn" onclick="closeModal('images')">关闭</button></div></div></div><div class="modal-backdrop" id="governance" onclick="backdrop(event,'governance')"><div class="modal"><h2>运行时容量告警</h2><p>教学实验集群 B 可用 CPU 低于配置阈值，可能影响新实验环境准备。</p><div class="sumline"><span>可用 CPU</span><strong>1,200 millicores</strong></div><div class="sumline"><span>可用内存</span><strong>6.4 GB</strong></div><div class="modal-actions"><button class="btn" onclick="closeModal('governance')">关闭</button><button class="btn primary" onclick="closeModal('governance');toast('运行时管理（演示）')">查看运行时</button></div></div></div>`;
}
function stripPageIntros(){
  document.querySelectorAll('.screen .head').forEach(head=>{
    const intro=head.querySelector(':scope > div:first-child');
    const controls=[...head.children].filter(child=>child!==intro&&child.matches('button, input, select, .actions')||child!==intro&&child.querySelector('button, input, select'));
    if(!controls.length){head.remove();return}
    head.className='page-actions';
    head.replaceChildren(...controls);
  });
}
function init(){renderStudent();renderTeacher();renderAdmin();renderEditor();renderSettings();renderExpandedScreens();stripPageIntros();renderModals();mountStudentCourseModal();renderNav();$('#portalSelect').addEventListener('change',event=>setPortal(event.target.value));document.querySelectorAll('[data-profile-action]').forEach(button=>button.addEventListener('click',()=>handleProfileAction(button.dataset.profileAction)));document.addEventListener('click',event=>{if(profileOpen&&!event.target.closest('.profile-menu-wrap'))closeProfileDrawer();if(!event.target.closest('.nav-group'))closeNavGroups()});lucide.createIcons();initCharts();window.addEventListener('resize',resizeCharts)}
document.addEventListener('DOMContentLoaded',init);
