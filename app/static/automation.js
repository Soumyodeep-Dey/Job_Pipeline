/* Phase 5: poll persisted task state; scheduling is performed by the worker. */
(() => {
  let refreshing = false;
  let taskSignature = '', scheduleSignature = '', notificationSignature = '';
  const terminal = new Set();
  const formatTime = value => new Date(value).toLocaleString();

  function taskCard(task) {
    const card = node('div', undefined, 'card');
    const names = task.payload.company_ids.map(id => companies.find(c => c.id === id)?.name || `Company ${id}`);
    card.append(node('strong', names.join(', ')), node('span', task.status, 'badge'),
      node('p', `Task ${task.id.slice(0,8)} · Attempt ${task.attempts}/3 · Queued ${formatTime(task.created_at)}`, 'muted'));
    if(task.status === 'queued') card.append(node('p', `Available after ${formatTime(task.available_at)}`, 'muted'));
    if(task.error) card.append(node('p', task.error));
    const controls = node('div', undefined, 'actions');
    if(task.status === 'queued') {
      const cancel = node('button', 'Cancel queued task', 'secondary');
      cancel.onclick = () => action(cancel, async () => {
        await send(`/discovery/tasks/${task.id}/cancel`, 'POST', {}); await refresh();
      });
      controls.append(cancel);
    }
    if(['failed','partial','cancelled'].includes(task.status)) {
      const retry = node('button', 'Queue a new attempt', 'secondary');
      retry.onclick = () => action(retry, async () => {
        await send('/discovery/tasks', 'POST', task.payload);
        notice('New task queued. The previous task history is preserved.'); await refresh();
      });
      controls.append(retry);
    }
    for(const [index, id] of task.run_ids.entries()) {
      const inspect = node('button', `View run ${index+1}`, 'secondary');
      inspect.onclick = () => action(inspect, async () => {
        const run = await api(`/discovery/runs/${id}`);
        result.replaceChildren(runCard(run));
      });
      controls.append(inspect);
    }
    const result = node('div');
    card.append(controls, result);
    return card;
  }

  function scheduleCard(schedule) {
    const card = node('div', undefined, 'card');
    card.append(node('strong', schedule.name), node('p',
      `${schedule.enabled ? 'Enabled' : 'Paused'} · Every ${schedule.interval_minutes} minutes · ${schedule.enabled ? 'Next due '+formatTime(schedule.next_run_at) : 'No future runs will be queued'}`));
    card.append(node('p', schedule.payload.company_ids.map(id => companies.find(c => c.id === id)?.name || `Company ${id}`).join(', '), 'muted'));
    const toggle = node('button', schedule.enabled ? 'Pause schedule' : 'Enable schedule', 'secondary');
    toggle.onclick = () => action(toggle, async () => {
      await send(`/discovery/schedules/${schedule.id}`, 'PATCH', {enabled:!schedule.enabled});
      notice(schedule.enabled ? 'Schedule paused. Already queued tasks remain; cancel them separately if needed.' : 'Schedule enabled. First run is due after its interval.');
      await refresh();
    });
    card.append(toggle);
    return card;
  }

  async function refresh() {
    if(refreshing) return;
    refreshing = true;
    try {
      const [health,tasks,schedules,notifications] = await Promise.all([
        api('/worker/health'),api('/discovery/tasks'),allPages('/discovery/schedules'),api('/notifications')]);
      $('worker-status').textContent = `Worker: ${health.status} · ${health.tasks.queued || 0} queued · ${health.tasks.running || 0} running`;
      if(taskSignature !== JSON.stringify([tasks,companies.length])) {
        taskSignature = JSON.stringify([tasks,companies.length]);
        $('task-list').replaceChildren(...tasks.map(taskCard));
        if(!tasks.length) $('task-list').append(node('p','No tasks yet. Queue discovery from Companies & discovery.','empty'));
      }
      if(scheduleSignature !== JSON.stringify([schedules,companies.length])) {
        scheduleSignature = JSON.stringify([schedules,companies.length]);
        $('schedule-list').replaceChildren(...schedules.map(scheduleCard));
        if(!schedules.length) $('schedule-list').append(node('p','No schedules configured.','muted'));
      }
      if(notificationSignature !== JSON.stringify(notifications)) {
        notificationSignature = JSON.stringify(notifications);
        $('notification-list').replaceChildren(...notifications.map(notification => {
        const card=node('div',undefined,'card');
        card.append(node('p', notification.message));
        const read=node('button','Mark read','secondary');
        read.onclick=()=>action(read,async()=>{await send(`/notifications/${notification.id}/read`,'POST',{});await refresh();});
        card.append(read);return card;
      }));
      if(!notifications.length) $('notification-list').append(node('p','No unread notifications.','muted'));
      }
      const newlyFinished = tasks.filter(t => ['completed','partial','failed'].includes(t.status) && !terminal.has(t.id));
      tasks.filter(t => ['completed','partial','failed'].includes(t.status)).forEach(t => terminal.add(t.id));
      if(newlyFinished.length) { await loadJobs(); await loadRuns(); }
    } catch(error) {
      $('worker-status').textContent = 'Worker status unavailable: ' + error.message;
    } finally { refreshing = false; }
  }

  $('schedule-form').onsubmit = event => {
    event.preventDefault();
    const payload = {name:$('schedule-name').value, interval_minutes:Number($('schedule-interval').value),
      enabled:false, discovery:{company_ids:[...selectedCompanies], max_jobs_per_company:Number($('discovery-limit').value), job_offset:Number($('discovery-offset').value)}};
    action($('schedule-form'), async () => {
      if(!payload.discovery.company_ids.length) throw new Error('Select companies in Companies & discovery first.');
      await send('/discovery/schedules','POST',payload);
      notice('Paused schedule created. Enable it when you want recurring discovery.');await refresh();
    });
  };
  $('refresh-tasks').onclick=()=>refresh();
  document.addEventListener('tasks-changed',refresh);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  setInterval(()=>{if(!document.hidden)refresh();},10000);
  refresh();
})();
