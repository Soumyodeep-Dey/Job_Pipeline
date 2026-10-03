/* Same-origin UI: the server remains the authority for scoring and approvals. */
const $ = id => document.getElementById(id);
const statuses = ['New','Shortlisted','Approved','Applied','Interview','Rejected','Offer','Withdrawn'];
let jobs = [], resumes = [], companies = [], coverage = [], offset = 0, selected = null, detailVersion = 0;
let jobsVersion = 0;
const selectedCompanies = new Set();
function node(tag, text, className) { const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(className) el.className = className; return el; }
function notice(text, error=false) { $('notice').textContent = text; $('notice').className = error ? 'error' : ''; }
async function api(path, options={}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
const send = (path, method, body) => api(path, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
async function action(control, work) {
  if(control.dataset.busy) return;
  control.dataset.busy = 'true';
  const controls = control.matches('form') ? [...control.querySelectorAll('button,input,select,textarea')] : [control];
  controls.forEach(el => el.disabled = true);
  try { await work(); } catch(error) { notice(error.message || 'Request failed. Check the API connection.', true); }
  finally { controls.forEach(el => el.disabled = false); delete control.dataset.busy; $('previous').disabled=offset===0; $('next').disabled=jobs.length<20; }
}
function option(value, text) { const el=node('option',text); el.value=value; return el; }
statuses.forEach(s => $('filter-status').append(option(s,s)));
function show(view) {
  if(view==='applications') loadApplications().catch(error=>notice(error.message,true));
  ['jobs','companies','resumes','automation','applications'].forEach(name => $(name+'-view').hidden = view !== name);
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active',b.dataset.view === view));
  $('page-title').textContent = {jobs:'Job review',companies:'Companies & discovery',resumes:'Résumé library',automation:'Background tasks',applications:'Applications & follow-ups'}[view];
}
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => show(b.dataset.view));
async function allPages(path, size=500) {
  let rows=[];
  for(let start=0;;start+=size) { const page=await api(`${path}?limit=${size}&offset=${start}`); rows.push(...page); if(page.length<size) return rows; }
}
async function loadJobs() {
  const version=++jobsVersion;
  const params=new URLSearchParams();
  for(const input of $('filters').elements) if(input.name && input.value.trim()) params.set(input.name,input.value.trim());
  params.set('offset',offset); params.set('limit',20);
  const result=await api('/jobs?'+params);
  if(version!==jobsVersion) return;
  jobs=result;
  $('page-label').textContent=`Page ${offset/20+1} · ${jobs.length} jobs`;
  $('previous').disabled=offset===0; $('next').disabled=jobs.length<20;
  renderJobs();
}
function renderJobs() {
  $('job-list').replaceChildren();
  if(!jobs.length) $('job-list').append(node('p','No jobs match this view and its filters. Check discovery run results for source errors, or switch to history to inspect excluded jobs.','empty'));
  for(const job of jobs) {
    const button=node('button',undefined,'job-card'+(selected?.job_id===job.job_id?' selected':''));
    button.append(node('small',job.company),node('strong',job.role),node('small',job.location || 'Location not specified'),node('br'),node('span',job.status,'badge'),node('small',`Suitability ${job.match_score ?? '—'} / 100`));
    button.onclick=()=>action(button,()=>openJob(job)); $('job-list').append(button);
  }
}
function jsonDetails(title, data) { const el=node('details'); el.append(node('summary',title),node('pre',JSON.stringify(data,null,2))); return el; }
async function openJob(job) {
  selected=job; const version=++detailVersion; renderJobs();
  $('detail').replaceChildren(node('p','Loading job evidence…','muted'));
  const id=encodeURIComponent(job.job_id);
  const [approval,history,evidence]=await Promise.all([api(`/jobs/${id}/approval`),api(`/jobs/${id}/resume-assessments`),fetch(`/jobs/${id}/discovery`).then(async r=>{if(r.status===404)return null; if(!r.ok)throw new Error('Could not load discovery evidence'); return r.json();})]);
  if(version!==detailVersion) return;
  const panel=$('detail'); panel.replaceChildren(node('p',job.company,'eyebrow'),node('h2',job.role),node('p',job.location || 'Location not specified','muted'));
  panel.append(node('span',approval.status,'badge'),node('span',`Approval: ${approval.method}`,'badge'));
  panel.append(node('p',`Résumé coverage: ${approval.resume_match_percent == null ? 'Unknown' : approval.resume_match_percent.toFixed(1)+'%'} · Suitability: ${job.match_score ?? 'Unknown'}`));
  if(job.source_url) { try { const url=new URL(job.source_url); if(['http:','https:'].includes(url.protocol)){const a=node('a','Open original posting ↗'); a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';panel.append(a);} } catch {} }
  const description=node('details'); description.open=true;description.append(node('summary','Job description'),node('p',evidence?.description || 'No discovery description is stored for this job. Use the original posting to verify requirements.','description'));panel.append(description);
  if(evidence) panel.append(jsonDetails('Discovery explanation & warnings',evidence.explanation));
  panel.append(jsonDetails('Résumé assessment history',history));
  const form=node('form'); const skills=node('textarea'); skills.value=job.required_skills || '';skills.maxLength=10000;
  const skillsLabel=node('label','Required skills (one per comma, semicolon or line)');skillsLabel.append(skills);
  const select=node('select');select.append(option('','Configured master / best available résumé'));resumes.forEach(r=>select.append(option(r.id,`${r.filename} · ${r.id.slice(0,8)}`)));
  const resumeLabel=node('label','Résumé to evaluate');resumeLabel.append(select);
  const assess=node('button','Save requirements & reassess');
  form.append(skillsLabel,resumeLabel,node('p','Reassessment can automatically approve at 80%+, or remove automatic approval below 80%. Coverage measures skill text, not overall hiring suitability.','muted'),assess);
  form.onsubmit=e=>{e.preventDefault();const body={required_skills:skills.value};if(select.value)body.resume_id=select.value;action(form,async()=>{const result=await send(`/jobs/${id}/resume-assessment`,'POST',body);notice(`Assessment saved. Status: ${result.status}.`);await refreshJob(job);});};panel.append(form);
  const statusForm=node('form'); const status=node('select');statuses.forEach(s=>status.append(option(s,s)));status.value=approval.status;
  const statusLabel=node('label','Tracking status');statusLabel.append(status);
  const human=node('input');human.type='checkbox';human.checked=approval.human_approval;human.style.width='auto';
  const humanLabel=node('label');humanLabel.style.display='block';humanLabel.append(human,document.createTextNode(' I have reviewed and manually approve this job'));
  statusForm.append(statusLabel,humanLabel,node('button','Save decision'));
  statusForm.onsubmit=e=>{e.preventDefault();const body={status:status.value,human_approval:human.checked};action(statusForm,async()=>{await send(`/jobs/${id}`,'PATCH',body);notice('Decision saved. No application was submitted.');await refreshJob(job);});};panel.append(statusForm);
  await renderPreparation(job,panel,version);
}
async function refreshJob(job) {
  // Fetch the current record even if its changed status removes it from the filter.
  const fresh=await api('/dashboard/jobs/'+encodeURIComponent(job.job_id));
  await loadJobs();await openJob(fresh);
}
$('filters').onsubmit=e=>{e.preventDefault();offset=0;selected=null;++detailVersion;$('detail').replaceChildren(node('p','Select a job to review.','empty'));action($('filters'),loadJobs);};
for(const [id,delta] of [['previous',-20],['next',20]]) $(id).onclick=()=>{offset=Math.max(0,offset+delta);action($(id),loadJobs);};
function renderCompanies() {
  $('company-list').replaceChildren();const search=$('company-search').value.toLowerCase();
  for(const c of companies.filter(c=>c.name.toLowerCase().includes(search))) {
    const label=node('label',undefined,'company-choice');const box=node('input');box.type='checkbox';box.value=c.id;box.checked=selectedCompanies.has(c.id);
    box.onchange=()=>{if(box.checked && selectedCompanies.size>=5){box.checked=false;notice('Choose up to five companies.',true);return;}if(box.checked)selectedCompanies.add(c.id);else selectedCompanies.delete(c.id);};
    const text=node('span',c.name);const report=coverage.find(r=>r.company_id===c.id);if(report?.missing_keyword_profile)text.append(node('small','Missing workbook keyword profile'));if(report?.missing_career_page)text.append(node('small','Missing career URL'));label.append(box,text);$('company-list').append(label);
  }
}
$('company-search').oninput=renderCompanies;
function runCard(run) {
  const card=node('div',undefined,'card');card.append(node('strong',`${run.status} · ${new Date(run.started_at).toLocaleString()}`));
  for(const r of run.results){card.append(node('p',`${r.company}: ${r.created} created · ${r.auto_approved || 0} auto-approved · ${r.duplicates} duplicates · ${r.status}`));if(r.next_offset!=null)card.append(node('p',`Continue ${r.company} with starting offset ${r.next_offset}.`,'muted'));}
  card.append(jsonDetails('Run details and source errors',run));return card;
}
async function loadRuns(){const runs=await api('/discovery/runs?limit=20');$('run-list').replaceChildren(...runs.map(runCard));if(!runs.length)$('run-list').append(node('p','No discovery runs yet.','empty'));}
$('discovery-form').onsubmit=e=>{e.preventDefault();const body={company_ids:[...selectedCompanies],max_jobs_per_company:Number($('discovery-limit').value),job_offset:Number($('discovery-offset').value)};action($('discovery-form'),async()=>{if(!body.company_ids.length)throw new Error('Select at least one company.');const task=await send('/discovery/tasks','POST',body);$('discovery-result').replaceChildren(node('p',`Task ${task.id} queued. Open Background tasks to follow progress.`));notice('Discovery queued. You can close the browser; the worker will continue.');document.dispatchEvent(new Event('tasks-changed'));});};
$('audit').onclick=()=>action($('discovery-form'),async()=>{if(!selectedCompanies.size)throw new Error('Select at least one company.');notice('Checking official career sources…');const result=await send('/discovery/source-audits','POST',{company_ids:[...selectedCompanies]});const report=jsonDetails('Career source audit',result);report.open=true;$('discovery-result').replaceChildren(report);notice('Source check finished.');});
async function loadResumes(){resumes=await api('/resumes');$('resume-count').textContent=`${resumes.length} versions`;$('resume-list').replaceChildren(...resumes.map(r=>{const card=node('div',undefined,'card');card.append(node('strong',r.filename),node('p',`Version ${r.id.slice(0,12)}`,'muted'));return card;}));if(!resumes.length)$('resume-list').append(node('p','No résumés imported yet. Upload a PDF or scan the folder.','empty'));}
async function importResume(file){const body=new FormData();if(file)body.append('file',file);notice('Importing résumés…');const result=await api('/imports/resumes',{method:'POST',body});$('resume-results').replaceChildren(...result.results.map(r=>node('p',`${r.filename}: ${r.status}${r.message?' — '+r.message:''}`)));await loadResumes();notice('Import finished. Existing decisions have not changed.');}
$('resume-form').onsubmit=e=>{e.preventDefault();const file=$('resume-file').files[0];action($('resume-form'),async()=>{if(!file)throw new Error('Choose a PDF.');if(file.size>10*1024*1024)throw new Error('The PDF exceeds 10 MB.');await importResume(file);$('resume-file').value='';});};
$('rescan').onclick=()=>action($('resume-form'),()=>importResume());
async function loadWorkspace(){notice('Loading workspace…');const results=await Promise.allSettled([loadJobs(),loadResumes(),loadRuns(),(async()=>{[companies,coverage]=await Promise.all([allPages('/companies'),allPages('/discovery/coverage')]);renderCompanies();})()]);const errors=results.filter(r=>r.status==='rejected');notice(errors.length?errors.map(r=>r.reason.message).join(' · '):'Workspace ready.',errors.length>0);}
$('refresh').onclick=()=>action($('refresh'),async()=>{await loadWorkspace();if(selected)await refreshJob(selected);});
loadWorkspace();
