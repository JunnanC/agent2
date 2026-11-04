const { chromium } = require('../../frontend/node_modules/playwright');
const path = require('path');
const { pathToFileURL } = require('url');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href);
 for(const key of ['overview','courses','students','teachers','images','resources','logs']){
  await page.evaluate(k=>go(k),key);await page.locator('h1').waitFor();
  if(key!=='overview')await page.screenshot({path:path.join(__dirname,'inspection',key+'.png'),fullPage:true});
 }
 await page.evaluate(()=>{go('students');confirmAccount('students','S-2026001')});
 await page.locator('#reason').fill('原型验证');await page.getByRole('button',{name:'确认禁用',exact:true}).click();
 if(!await page.evaluate(()=>students[0].status==='已禁用'&&logs[0].type==='账号禁用'))throw Error('禁用同步失败');
 await page.evaluate(()=>confirmAccount('students','S-2026001'));await page.getByRole('button',{name:'确认恢复',exact:true}).click();
 await page.evaluate(()=>{go('courses');confirmCourse('CRS-26001')});await page.getByRole('button',{name:'确认下架',exact:true}).click();
 if(!await page.locator('#error').textContent())throw Error('下架原因未校验');
 await page.locator('#reason').fill('原型课程违规演示');await page.getByRole('button',{name:'确认下架',exact:true}).click();
 if(!await page.evaluate(()=>courses[0].status==='已下架'&&logs[0].type==='课程下架'))throw Error('下架同步失败');
 await page.evaluate(()=>{go('images');imageForm()});
 for(const [k,v] of Object.entries({name:'验证镜像',address:'registry.example.edu/labs/test',version:'v1',description:'验证新增配置'}))await page.locator(`[name="${k}"]`).fill(v);
 await page.getByRole('button',{name:'保存镜像',exact:true}).click();
 if(!await page.evaluate(()=>images.length===5&&logs[0].type==='镜像新增'))throw Error('新增失败');
 await page.evaluate(()=>confirmImage('IMG-005'));await page.getByRole('button',{name:'确认停用',exact:true}).click();
 if(!await page.evaluate(()=>images[4].status==='停用'))throw Error('停用失败');
 await page.evaluate(()=>{go('students');query='不存在';renderList()});
 if(!await page.locator('.empty').count())throw Error('空结果失败');
 await page.evaluate(()=>{query='';renderList();turn(1)});if(!await page.evaluate(()=>page===2))throw Error('分页失败');
 await page.evaluate(()=>{go('resources');resourceTab='nodes';renderResources()});
 await page.screenshot({path:path.join(__dirname,'inspection/resources-nodes.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>go('overview'));
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('移动端溢出');
 await browser.close();if(errors.length)throw Error(errors.join('\n'));console.log('PASS: 七页渲染、账号禁用恢复、下架校验、镜像新增停用、日志同步、搜索空状态、分页、移动端布局；无脚本错误');
})().catch(e=>{console.error(e);process.exit(1)});
