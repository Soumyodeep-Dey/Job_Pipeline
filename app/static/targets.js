/* Persist preferences on the server; the worker reads them at run start. */
(() => {
  function render(settings) {
    $('target-roles').value = settings.target_roles.join('\n');
    $('target-work').value = settings.india_work_preference;
    $('target-state').textContent = `${settings.enabled_batches}/${settings.total_batches} daily company batches enabled. External submission: manual.`;
  }
  api('/target-settings').then(render).catch(error => notice(error.message, true));
  $('target-form').onsubmit = event => {
    event.preventDefault();
    const body = {target_roles: $('target-roles').value.split('\n').map(s => s.trim()).filter(Boolean),
      india_work_preference: $('target-work').value};
    action($('target-form'), async () => {
      render(await send('/target-settings', 'PUT', body));
      offset = 0;
      await loadJobs();
      if(selected) await openJob(selected);
      notice('Designations saved. Future runs use these roles; previous run evidence and submitted applications remain historical.');
    });
  };
  for(const [id, enabled] of [['target-start', true], ['target-pause', false]]) {
    $(id).onclick = () => action($(id), async () => {
      render(await send('/target-settings/automation', 'PUT', {enabled}));
      notice(enabled ? 'Daily discovery enabled for imported companies. Keep Docker running.' : 'Target discovery paused; queued target batches cancelled. A running batch can finish.');
    });
  }
})();
