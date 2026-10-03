/* Preparation stays on this server. No employer forms or messages are sent. */
function labelled(text, input) { const label=node('label',text);label.append(input);return label; }
function inputField(type, value='') { const input=node('input');input.type=type;input.value=value;return input; }
function checkField(text, checked=false) { const input=inputField('checkbox');input.checked=checked;input.style.width='auto';return [labelled(text+' ',input),input]; }
async function renderPreparation(job, panel, version) {
  const id=encodeURIComponent(job.job_id), path=`/jobs/${id}/preparation`;
  const state=await api(path);
  if(version!==detailVersion) return;
  const prep=state.preparation;
  const section=node('section',undefined,'card');section.append(node('h2','Application preparation'));
  section.append(node('p',state.ready?'Ready to record your external submission.':state.blockers.join(' · '),'muted'));
  if(prep?.submitted_on) {
    section.append(node('p',`Submitted ${prep.submitted_on} via ${prep.channel}. Reference: ${prep.reference || '—'}`));
    section.append(jsonDetails('Frozen submission record',prep.submission_snapshot));
    const form=node('form'), date=inputField('date',prep.follow_up_on || '');
    const [doneLabel,done]=checkField('Follow-up completed',prep.follow_up_done);
    form.append(labelled('Follow-up date (clear to remove)',date),doneLabel,node('button','Save follow-up'));
    form.onsubmit=e=>{e.preventDefault();action(form,async()=>{await send(`/jobs/${id}/follow-up`,'PATCH',{follow_up_on:date.value||null,done:done.checked});notice('Follow-up saved. No message was sent.');await refreshJob(job);await loadApplications();});};
    section.append(form);panel.append(section);return;
  }
  const form=node('form'), resume=node('select');resume.required=true;
  resume.append(option('','Select the résumé you will use'));
  resumes.forEach(r=>resume.append(option(r.id,`${r.filename} · ${r.id.slice(0,12)}`)));
  resume.value=prep?.resume_id || '';
  const facts=node('textarea');facts.rows=5;facts.maxLength=20000;
  facts.placeholder='Built a Python API | Project README or résumé page 1';
  facts.value=(prep?.verified_facts || []).map(f=>`${f.text} | ${f.evidence}`).join('\n');
  const [confirmedLabel,confirmed]=checkField('I confirm these optional facts are accurate',Boolean(prep?.verified_facts?.length));
  const checklist={};
  form.append(labelled('Résumé version',resume),labelled('Optional profile facts: one fact | evidence per line',facts),confirmedLabel);
  for(const [key,text] of [['posting_open','Posting is still open'],['location_eligible','I meet location / work eligibility'],['documents_ready','Selected résumé and required documents are ready']]) {
    const [label,input]=checkField(text,prep?.checklist[key]);checklist[key]=input;form.append(label);
  }
  const draft=node('textarea');draft.rows=8;draft.maxLength=20000;draft.value=prep?.draft || '';
  const notes=node('textarea');notes.maxLength=10000;notes.value=prep?.notes || '';
  form.append(labelled('Editable application draft (optional)',draft),labelled('Private preparation notes',notes));
  form.append(node('p','Saving evaluates this exact résumé. Checklist items confirm practical readiness; 80%+ coverage needs no manual approval. Keep the original PDF available to upload on the employer site.','muted'));
  form.append(node('button','Save preparation'));
  form.onsubmit=e=>{e.preventDefault();action(form,async()=>{
    const verified_facts=facts.value.split('\n').filter(l=>l.trim()).map(line=>{const split=line.indexOf('|');if(split<1)throw new Error('Each fact needs a | followed by its evidence.');return {text:line.slice(0,split).trim(),evidence:line.slice(split+1).trim(),confirmed:confirmed.checked};});
    if(verified_facts.length && !confirmed.checked)throw new Error('Confirm the facts are accurate, or remove them.');
    await send(path,'PUT',{resume_id:resume.value,verified_facts,checklist:Object.fromEntries(Object.entries(checklist).map(([k,v])=>[k,v.checked])),draft:draft.value,notes:notes.value});
    notice('Preparation saved and selected résumé evaluated.');await refreshJob(job);
  });};
  const generate=node('button','Make template from saved facts','secondary');generate.type='button';
  generate.onclick=()=>action(generate,async()=>{const result=await send(path+'/draft','POST',{});draft.value=result.draft;notice('Template inserted. Edit and save the preparation to keep it. Nothing was sent.');});
  form.append(generate);section.append(form);
  if(prep) {
    const record=node('form'), date=inputField('date',new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'}));date.required=true;
    const channel=inputField('text','Employer career site');channel.required=true;channel.maxLength=100;
    const reference=inputField('text');reference.maxLength=1000;
    const follow=inputField('date');
    const [confirmationLabel,confirmation]=checkField('I have already submitted this application externally');confirmation.required=true;
    record.append(node('h3','Record a completed application'),node('p','Uses the saved preparation above. Save any edits before recording.','muted'),labelled('Submission date (India calendar date)',date),labelled('Channel',channel),labelled('Confirmation reference (optional)',reference),labelled('Follow-up date (optional)',follow),confirmationLabel,node('button','Record application'));
    record.onsubmit=e=>{e.preventDefault();action(record,async()=>{await send(`/jobs/${id}/application`,'POST',{confirmed_submitted:confirmation.checked,submitted_on:date.value,channel:channel.value,reference:reference.value,follow_up_on:follow.value||null});notice('Application recorded; saved preparation frozen.');await refreshJob(job);await loadApplications();});};
    section.append(record);
  }
  panel.append(section);
}
async function loadApplications() {
  const rows=await allPages('/applications',200);
  const visible=$('followups-only').checked?rows.filter(r=>r.due):rows;
  $('application-list').replaceChildren();
  if(!visible.length)$('application-list').append(node('p','No recorded applications in this view. Prepare a job in Job review, then record it after submitting externally.','empty'));
  for(const row of visible) {
    const card=node('div',undefined,'card');
    card.append(node('strong',`${row.company} · ${row.role}`),node('p',`${row.status} · Submitted ${row.submitted_on} · Follow-up ${row.follow_up_on || 'not scheduled'}${row.follow_up_done?' (completed)':''}`));
    if(row.due)card.append(node('span','Follow-up due','badge'));
    const open=node('button','Open application','secondary');open.onclick=()=>action(open,async()=>{const job=await api('/dashboard/jobs/'+encodeURIComponent(row.job_id));show('jobs');await openJob(job);});card.append(open);
    $('application-list').append(card);
  }
}
$('refresh-applications').onclick=()=>action($('refresh-applications'),loadApplications);
$('followups-only').onchange=()=>action($('refresh-applications'),loadApplications);
