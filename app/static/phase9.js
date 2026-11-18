/* Confirmed answers and reviewed requirements. No external form submission. */
const profileFields=[
  ['full_name','Full name','text'],['given_name','First name for employer forms','text'],['family_name','Last name for employer forms','text'],['email','Email address','email'],['phone','Phone number','text'],
  ['current_city','Current city','text'],['linkedin_url','LinkedIn HTTPS URL','url'],['portfolio_url','Portfolio HTTPS URL','url'],
  ['india_work_authorized','Currently authorized to work in India','bool'],['requires_sponsorship','Require employer sponsorship','bool'],
  ['willing_relocate_india','Willing to relocate within India','bool'],['work_modes','Accepted work arrangements','modes'],
  ['experience_years','Relevant professional experience in years','number'],['notice_days','Notice period in calendar days','number'],
  ['available_from','Earliest confirmed availability date','date'],['expected_ctc_lpa','Expected annual CTC in INR lakhs per annum','number']];
function valueControl(type,value) {
  if(type==='bool' || type==='sponsorship' || type==='mode') {
    const el=node('select'); el.append(option('','Unknown / not stated'));
    const opts=type==='sponsorship'?[['true','No sponsorship offered'],['false','Sponsorship explicitly offered']]:type==='bool'?[['true','Yes'],['false','No']]:[['remote','Remote'],['hybrid','Hybrid'],['on_site','On site']];
    opts.forEach(([v,t])=>el.append(option(v,t))); el.value=value==null?'':String(value);return el;
  }
  if(type==='list') {const el=node('textarea');el.rows=3;el.value=(value||[]).join('\n');return el;}
  if(type==='modes') {const el=node('select');el.multiple=true;[['remote','Remote'],['hybrid','Hybrid'],['on_site','On site']].forEach(([v,t])=>{const o=option(v,t);o.selected=(value||[]).includes(v);el.append(o);});return el;}
  const el=inputField(type,value??'');if(type==='number'){el.min='0';el.step='any';}return el;
}
function valueFrom(el,type) {
  if(type==='list')return el.value.split('\n').map(v=>v.trim()).filter(Boolean);
  if(type==='modes')return [...el.selectedOptions].map(o=>o.value);
  if(el.value.trim()==='')return null;
  if(type==='bool' || type==='sponsorship')return el.value==='true';
  if(type==='number')return Number(el.value);
  return el.value.trim();
}
async function loadApplicantProfile() {
  const saved=await api('/applicant-profile'), form=node('form',undefined,'card'), fields={};
  form.append(node('p',saved.version?`Confirmed version ${saved.version} · ${saved.confirmed_at}`:'No confirmed applicant profile yet.'));
  for(const [key,label,type] of profileFields) {const el=valueControl(type,saved.data[key]); fields[key]=el;form.append(labelled(label,el));}
  const [label,confirmed]=checkField('I confirm the entered answers are accurate; blank fields remain unknown');confirmed.required=true;
  form.append(label,node('button','Save confirmed profile'));
  form.onsubmit=e=>{e.preventDefault();const data=Object.fromEntries(profileFields.map(([key,_,type])=>[key,valueFrom(fields[key],type)]));
    action(form,async()=>{await send('/applicant-profile','PUT',{expected_version:saved.version,confirmed:confirmed.checked,data});notice('Confirmed profile saved. Current eligibility checks use this new version; submitted snapshots stay unchanged.');await loadApplicantProfile();});};
  const history=await api('/applicant-profile/history'), answers=await api('/applicant-profile/answers');
  $('profile-content').replaceChildren(form,jsonDetails('Reusable answers with exact units',answers),jsonDetails('Confirmed profile history',history));
}
async function renderEligibility(job,panel,version) {
  const path=`/jobs/${encodeURIComponent(job.job_id)}`;
  const [requirements,result,answerSet]=await Promise.all([api(path+'/requirements'),api(path+'/eligibility'),api(path+'/application-answers')]);
  if(version!==detailVersion)return;
  const section=node('section',undefined,'card');section.append(node('h2','Requirements and eligibility'),node('strong',result.status.replaceAll('_',' ')),node('p',result.note,'muted'));
  for(const check of result.checks)section.append(node('p',`${check.state.toUpperCase()} · ${check.message}`));
  section.append(jsonDetails('Required and preferred skill evidence',{required:result.required_skill_coverage,preferred_matches:result.preferred_skill_matches}));
  section.append(jsonDetails('Confirmed answers for this application',answerSet.answers));
  const profile=node('button','Review applicant profile','secondary');profile.type='button';profile.onclick=()=>show('profile');section.append(profile);
  const recheck=node('button','Recheck and save eligibility evidence','secondary');recheck.type='button';
  recheck.onclick=()=>action(recheck,async()=>{await send(path+'/eligibility/assess','POST',{});notice('Eligibility assessment saved. Job status and résumé approval were not changed.');await refreshJob(job);});section.append(recheck);
  const assessmentHistory=await api(path+'/eligibility/history');if(version!==detailVersion)return;
  section.append(jsonDetails('Eligibility assessment history',assessmentHistory));
  if(['Applied','Interview','Offer','Withdrawn'].includes(job.status)) {section.append(node('p','Submitted requirements are frozen. This view compares current facts; the original submission snapshot remains unchanged.'));panel.append(section);return;}
  const data=requirements.review_current?requirements.reviewed:requirements.suggested.data;
  section.append(node('h3','Confirm the actual job requirements'),node('p',requirements.review_current?`Reviewed version ${requirements.version}`:'Suggestions need review against the live posting. Do not remove unresolved conditions unless you have resolved them.'));
  section.append(jsonDetails('Extraction source evidence',requirements.suggested.evidence));
  const specs=[['required_skills','Mandatory skills — one per line','list'],['preferred_skills','Preferred skills — one per line','list'],
    ['minimum_experience_years','Minimum relevant experience in years','number'],['india_eligible','Posting accepts India-based applicants','bool'],
    ['work_mode','Required work arrangement','mode'],['city','Required office city','text'],['no_sponsorship','Employer sponsorship policy','sponsorship'],
    ['maximum_notice_days','Maximum accepted notice period in days','number'],['start_by','Required start date','date'],
    ['unresolved_requirements','Unresolved conditions — keep any unverified degree, certification or other requirement here','list']];
  const form=node('form'), fields={};for(const [key,label,type] of specs){const el=valueControl(type,data[key]);fields[key]=el;form.append(labelled(label,el));}
  const note=node('textarea');note.required=true;note.maxLength=3000;note.placeholder='Explain the source and any corrections; distinguish total experience from domain-specific requirements.';
  const [confirmation,confirmed]=checkField('I reviewed these requirements against the current posting');confirmed.required=true;
  form.append(labelled('Review evidence and corrections',note),confirmation,node('p','Saving a review updates mandatory skills and invalidates earlier résumé approval. Recreate and approve the job-specific résumé afterwards.','muted'),node('button','Save reviewed requirements'));
  form.onsubmit=e=>{e.preventDefault();const data=Object.fromEntries(specs.map(([key,_,type])=>[key,valueFrom(fields[key],type)]));
    action(form,async()=>{await send(path+'/requirements','PUT',{expected_version:requirements.version,source_hash:requirements.source_hash,confirmed:confirmed.checked,review_note:note.value,data});notice('Requirements reviewed. Recheck eligibility and approve a fresh résumé version before applying.');await refreshJob(job);});};
  section.append(form);panel.append(section);
}
