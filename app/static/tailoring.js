/* Wording approval is separate from job-match approval. No submissions are sent. */
async function renderResumeReview(job, panel, version) {
  const path=`/jobs/${encodeURIComponent(job.job_id)}/resume-proposals`;
  const history=await api(path);
  if(version!==detailVersion) return;
  const current=history[0], section=node('section',undefined,'card');
  section.append(node('h2','Review job-specific résumé'),node('p','Propose → review wording → approve → download. An 80% job match never approves résumé edits.'));
  if(['Applied','Interview','Offer','Withdrawn'].includes(job.status)) {
    section.append(node('p','Application history is preserved. New proposals are disabled for submitted jobs.'));
    if(current?.status==='approved') addDownloads(current);
    panel.append(section); return;
  }
  const select=node('select');
  resumes.forEach(r=>select.append(option(r.id,r.filename)));
  if(current) select.value=current.master_id;
  const create=node('button',current?'Create fresh proposal from master':'Create proposal from master','secondary');
  create.type='button';
  create.onclick=()=>action(create,async()=>{
    await send(path,'POST',{resume_id:select.value});
    notice('New proposal awaits your approval. Previous approval cannot be reused.'); await refreshJob(job);
  });
  section.append(labelled('Master résumé',select),create);
  if(!current) {panel.append(section); return;}
  section.append(node('h3',`Version ${current.id.slice(0,8)} · ${current.status}`));
  if(current.stale_reason) section.append(node('p',current.stale_reason,'error'));
  section.append(node('p',current.evidence.automatic_change));
  section.append(node('p',current.evidence.review_note,'muted'));
  if(!current.evidence.requirements.length) section.append(node('p','Required skills are unknown. This proposal retains the master text; inspect the live posting and requirements before applying.'));
  for(const row of current.evidence.requirements) {
    const item=node('div',undefined,'card');
    item.append(node('strong',`${row.requirement}: ${row.supported?'text evidence found':'not supported'}`));
    if(row.source_quote) item.append(node('p',row.source_quote));
    section.append(item);
  }
  for(const [title,text] of [['Original master',current.original],['Proposed final text',current.proposed],['Before and after changes',current.diff || 'No wording changes']]) {
    const details=node('details');details.append(node('summary',title));
    const pre=node('pre',text);pre.style.whiteSpace='pre-wrap';pre.style.overflowWrap='anywhere';details.append(pre);section.append(details);
  }
  if(current.evidence.edits.length) section.append(jsonDetails('Edit reasons and source quotes',current.evidence.edits));
  const editForm=node('form');editForm.append(node('h3','Propose a wording revision'));
  const fields={};
  for(const [key,label] of [['before','Exact passage in proposed text'],['after','Replacement wording'],['source_quote','Supporting quote copied from original master'],['reason','Why this change helps this job']]) {
    const field=node('textarea');field.rows=2;field.required=true;field.maxLength=key==='reason'?1000:4000;fields[key]=field;editForm.append(labelled(label,field));
  }
  editForm.append(node('p','Evidence quotes are checked against the master. You must still verify that revised claims are actually supported. Revisions create a new pending version.','muted'),node('button','Save revision for review'));
  editForm.onsubmit=e=>{e.preventDefault();const edit=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value]));action(editForm,async()=>{
    await send(path,'POST',{resume_id:current.master_id,edits:[...current.evidence.edits,edit]});
    notice('Revision saved. Review and approve the new version before exporting.');await refreshJob(job);
  });};
  section.append(editForm);
  if(current.status==='pending' && !current.stale_reason) {
    const [label,confirmed]=checkField('I reviewed this exact version and confirm its claims are truthful and supported');section.append(label);
    const approve=node('button','Approve this résumé and create exports'), reject=node('button','Reject this version','secondary');
    approve.onclick=()=>action(approve,async()=>{
      if(!confirmed.checked)throw new Error('Review the proposed text and confirm its claims first.');
      await send(`${path}/${current.id}/review`,'POST',{decision:'approve',content_sha256:current.content_sha256,confirmed_truthful:true});
      notice('Exact version approved. PDF and DOCX exports are ready; no application was sent.');await refreshJob(job);
    });
    reject.onclick=()=>action(reject,async()=>{await send(`${path}/${current.id}/review`,'POST',{decision:'reject',content_sha256:current.content_sha256});await refreshJob(job);});
    section.append(approve,reject);
  }
  if(current.status==='approved' && !current.stale_reason) addDownloads(current);
  const older=node('details');older.append(node('summary',`Version history (${history.length})`));
  history.forEach(p=>older.append(node('p',`${p.id.slice(0,8)} · ${p.status} · ${p.created_at}${p.reviewed_by?' · reviewed by '+p.reviewed_by:''}`)));section.append(older);
  panel.append(section);
  function addDownloads(proposal) {
    for(const format of ['pdf','docx']) {
      const link=node('a',`Download approved ${format.toUpperCase()}`);link.href=`${path}/${proposal.id}/export/${format}`;link.style.marginRight='1rem';section.append(link);
    }
  }
}
