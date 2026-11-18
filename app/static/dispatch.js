let questionSignature = '';
let dispatchLoading = false;

function questionPanel(data) {
  const box = $('application-questions');
  const signature = JSON.stringify(data);
  if (signature === questionSignature || box.contains(document.activeElement)) return;
  questionSignature = signature;
  box.replaceChildren(node('h2', 'Answers needed (' + data.pending.length + ')'),
    node('p', 'Questions from employer forms appear here. Saving your answer lets the sender recheck that job automatically. Employer text is displayed as information only.'));
  for (const question of data.pending) {
    const spec = question.spec, form = node('form', undefined, 'card');
    form.append(node('h3', question.role + ' · ' + (question.location || '')),
      node('p', spec.prompt), node('p', spec.context, 'muted'));
    const link = node('a', 'View employer application');
    link.href = question.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; form.append(link);
    const label = node('label', spec.required ? 'Your answer (required)' : 'Your answer (optional — blank leaves it unanswered)');
    let input;
    if (spec.options.length) {
      input = node('select');
      const blank = node('option', spec.required ? 'Choose an answer' : 'Leave blank'); blank.value = ''; input.append(blank);
      for (const choice of spec.options) { const option = node('option', choice); option.value = choice; input.append(option); }
    } else {
      input = node('textarea'); input.rows = 3; input.maxLength = 6000;
    }
    input.required = spec.required; label.append(input); form.append(label);
    const reuseLabel = node('label'), reuse = node('input'); reuse.type = 'checkbox';
    reuse.checked = false; reuse.disabled = spec.kind === 'checkbox';
    reuseLabel.append(reuse, document.createTextNode(' Reuse this answer for the exact same question and choices on future jobs. Choose this only if your answer is independent of the employer and role.'));
    form.append(reuseLabel);
    if (spec.kind === 'checkbox') form.append(node('p', 'This declaration applies only to this job.'));
    const save = node('button', 'Confirm answer and resume automatically'); save.type = 'submit'; form.append(save);
    form.onsubmit = event => {
      event.preventDefault();
      action(form, async () => {
        await send('/dispatch/questions/' + encodeURIComponent(question.id), 'PUT', {
          answer: input.value, reuse: reuse.checked, confirmed: true, expected_profile_version: data.profile_version
        });
        document.activeElement?.blur(); questionSignature = '';
        await loadDispatch(); notice('Answer saved. Sending will resume when this job is ready and a daily slot is available.');
      });
    };
    box.append(form);
  }
  if (!data.pending.length) box.append(node('p', 'No unanswered application questions.'));
  const library = node('details'); library.append(node('summary', 'Saved reusable answers (' + data.saved_answers.length + ')'));
  for (const answer of data.saved_answers) {
    const card = node('div', undefined, 'card');
    card.append(node('strong', answer.spec.prompt), node('p', answer.answer || '(Leave blank)'),
      node('p', answer.current ? 'Available for exact matches.' : 'Inactive because your applicant profile changed.'));
    const forget = node('button', 'Forget for future jobs', 'secondary');
    forget.onclick = () => action(forget, async () => {
      await api('/dispatch/answers/' + encodeURIComponent(answer.fingerprint), {method:'DELETE'});
      document.activeElement?.blur(); questionSignature = ''; await loadDispatch();
    });
    card.append(forget); library.append(card);
  }
  box.append(library);
}

async function loadDispatch() {
  if (dispatchLoading) return;
  dispatchLoading = true;
  try {
    const [state, questions] = await Promise.all([api('/dispatch'), api('/dispatch/questions')]), box = $('dispatch-control');
    if (!$('application-questions')) { const q = node('div', undefined, 'card'); q.id = 'application-questions'; box.after(q); }
    if (!$('question-alert')) {
      const alert = node('button'); alert.id = 'question-alert';
      alert.onclick = () => { document.querySelector('[data-view="automation"]').click(); $('application-questions').scrollIntoView(); };
      $('notice').after(alert);
    }
    const alert = $('question-alert'); alert.hidden = !questions.pending.length;
    alert.textContent = questions.pending.length + ' application question(s) need your answer — open inbox';
    const schedule = state.schedule;
    box.replaceChildren(node('h2', 'Automatic applications'),
      node('p', state.enabled ? 'Sending enabled for eligible, approved jobs.' : 'Sending paused.'),
      node('p', 'Daily from 9:00 AM IST · up to ' + schedule.daily_limit + ' applications · ' + schedule.used + ' slots used today · ' + schedule.remaining + ' remaining.'),
      node('p', !schedule.window_open ? 'Waiting for 9:00 AM India time.' :
        !schedule.remaining ? 'Daily limit reached. Next allowance starts at 9:00 AM India time.' : 'The sender checks ready jobs every 30 seconds.'));
    const toggle = node('button', state.enabled ? 'Pause automatic applications' : 'Enable automatic applications');
    toggle.onclick = () => action(toggle, async () => { await send('/dispatch', 'PUT', {enabled:!state.enabled}); await loadDispatch(); });
    box.append(toggle, node('p', 'Keep Docker and your computer running and awake. Review each job’s requirements and résumé. Fewer than five may be sent when fewer jobs are ready. Questions and uncertain results do not block other ready jobs.'));
    for (const record of state.attempts) {
      const line = node('p', record.role + ' · ' + record.state + ' · ' + record.message);
      if (record.state === 'needs_review') {
        const retry = node('button', 'Recheck this job');
        retry.onclick = () => action(retry, async () => { await send('/jobs/' + encodeURIComponent(record.job_id) + '/dispatch/recheck', 'POST', {}); await loadDispatch(); });
        line.append(retry);
      }
      box.append(line);
    }
    questionPanel(questions);
  } finally { dispatchLoading = false; }
}
loadDispatch().catch(e => notice(e.message, true));
setInterval(() => { if (!document.hidden) loadDispatch().catch(e => notice('Application status unavailable: ' + e.message, true)); }, 15000);
