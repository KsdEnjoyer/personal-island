(() => {
  let nextId = 10;
  const now = new Date();
  const at = days => new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, 18).toISOString();
  const base = { notes: null, reminder_at: null, priority: 0, status: 'open',
    created_at: now.toISOString(), completed_at: null, notification_sent_at: null };
  window.qaTasks = [
    { ...base, id: 1, title: 'Проверить напоминания', due_at: at(-1), priority: 1 },
    { ...base, id: 2, title: 'Собрать первую версию', notes: 'Дизайн, движение и немного внимания к деталям.', due_at: at(0) },
    { ...base, id: 3, title: 'Протестировать на втором мониторе', due_at: at(1) },
    { ...base, id: 4, title: 'Записать идеи для островка', due_at: null },
    { ...base, id: 5, title: 'Подготовить рабочее окружение', due_at: at(0), status: 'done' },
  ];
  window.qaCalls = [];
  window.qaClipboard = [];
  window.qaNotes = [];
  window.qaClipboardEnabled = true;
  window.qaMedia = { sessions: [], session_id: null, source: '', title: '', artist: '', artwork: null, playing: false, position: 0, duration: 0, can_toggle: false, can_previous: false, can_next: false };
  window.qaWeather = { data: null, stale: false, error: null };
  let callbackId = 0;
  let generation = 0;
  const callbacks = new Map();
  const listeners = new Map();
  window.qaEmit = (event, payload) => { const handler = listeners.get(event); if(handler) callbacks.get(handler)({event,id:handler,payload}); };
  window.qaReveal = (reason = 'manual') => {
    generation++;
    const handler = listeners.get('island-reveal');
    if (handler) callbacks.get(handler)({ event: 'island-reveal', id: handler, payload: {generation, reason} });
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: (_event, id) => callbacks.delete(id) };
  window.__TAURI_INTERNALS__ = { invoke: async (cmd, args = {}) => {
    window.qaCalls.push({ cmd, args, time: performance.now() });
    if (window.qaFail === cmd) throw 'QA simulated failure';
    if (cmd === 'plugin:event|listen') { listeners.set(args.event, args.handler); return args.handler; }
    if (cmd === 'plugin:event|unlisten') { listeners.delete(args.event); return; }
    if (cmd === 'register_island_shortcut' && window.qaStartup) { window.qaReveal('startup'); return; }
    if (['register_island_shortcut','set_island_shortcut_editing','hide_island','set_island_appearance'].includes(cmd)) return;
    if (cmd === 'toggle_island_shortcut') { window.qaEmit('island-toggle', null); return; }
    if (cmd === 'reveal_island_shortcut') { window.qaReveal('manual'); return; }
    if (cmd === 'show_reminder_island') {
      return {generation:++generation,expanded:document.querySelector('.dashboard')?.getAttribute('aria-hidden')==='false'};
    }
    if (cmd === 'acknowledge_island_reminder') {
      const task=qaTasks.find(task=>task.id===args.id && task.reminder_at===args.reminderAt && task.status==='open' && !task.notification_sent_at);
      if (!task) return false;
      task.notification_sent_at=new Date().toISOString();return true;
    }
    if (cmd === 'acknowledge_island_review') {
      const task=qaTasks.find(task=>task.id===args.id && task.reminder_at===args.reminderAt && task.status==='open' && !task.notification_sent_at && Date.parse(task.reminder_at)<=Date.now());
      if (!task) return false;
      task.notification_sent_at=new Date().toISOString();return true;
    }
    if (cmd === 'finish_island_reminder') return;
    if (cmd === 'get_media_state') return structuredClone(window.qaMedia);
    if (cmd === 'start_yandex_music') {
      if (window.qaLaunchDelay) await new Promise(resolve=>setTimeout(resolve,window.qaLaunchDelay));
      window.qaMedia = {sessions:[{id:'ru.yandex.desktop.music',label:'Яндекс Музыка'}],session_id:'ru.yandex.desktop.music',source:'Яндекс Музыка',title:'QA resumed track',artist:'QA Artist',artwork:null,playing:true,position:0,duration:200,can_toggle:true,can_previous:true,can_next:true};
      return structuredClone(window.qaMedia);
    }
    if (cmd === 'get_widget_summary') return {notes:qaNotes.filter(n=>n.category==='notes').length,ideas:qaNotes.filter(n=>n.category==='ideas').length,shopping:qaNotes.filter(n=>n.category==='shopping').length,clipboard:Math.min(9,qaClipboard.length),pinned:qaClipboard.filter(e=>e.pinned).length,capturing:qaClipboardEnabled};
    if (cmd === 'set_island_overlay') { window.qaOverlayOpen=args.open; return; }
    if (cmd === 'set_audio_reactivity') { window.qaAudioEnabled=args.enabled; return; }
    if (cmd === 'get_weather') return structuredClone(window.qaWeather);
    if (cmd === 'player_volume') {
      if (args.level === null && window.qaVolumeReadDelay) await new Promise(resolve=>setTimeout(resolve,window.qaVolumeReadDelay));
      if (args.level !== null && window.qaVolumeDelay) await new Promise(resolve=>setTimeout(resolve,window.qaVolumeDelay));
      window.qaVolume = args.level ?? window.qaVolume ?? .65;
      return { available: window.qaVolumeAvailable !== false, level: window.qaVolume, muted: false, scope: 'player' };
    }
    if (cmd === 'open_weather_source') return;
    if (cmd === 'media_command') { if(args.action === 'toggle') window.qaMedia.playing = !window.qaMedia.playing; return; }
    if (cmd === 'open_yandex_music' || cmd === 'copy_clipboard_entry' || cmd === 'paste_to_previous_window') return;
    if (cmd === 'list_clipboard') {
      let entries=[...qaClipboard].sort((a,b)=>b.captured_at-a.captured_at || b.id-a.id);
      entries=args.pinnedOnly ? entries.filter(e=>e.pinned) : entries.slice(0,9);
      return {enabled:qaClipboardEnabled,entries:structuredClone(entries.filter(e=>!args.search || (e.text || 'изображение картинка image').toLowerCase().includes(args.search.toLowerCase())))};
    }
    if (cmd === 'set_clipboard_enabled') { window.qaClipboardEnabled = args.enabled; return; }
    if (cmd === 'pin_clipboard') { window.qaClipboard.find(e => e.id === args.id).pinned = args.pinned; return; }
    if (cmd === 'delete_clipboard') { window.qaClipboard = window.qaClipboard.filter(e => e.id !== args.id); return; }
    if (cmd === 'list_tasks') return structuredClone(window.qaTasks);
    if (cmd === 'list_notes') return structuredClone(window.qaNotes);
    if (cmd === 'save_note') {
      if (window.qaNotesDelay) await new Promise(resolve=>setTimeout(resolve,window.qaNotesDelay));
      const current = window.qaNotes.find(note=>note.id === args.id);
      if (args.id && (!current || current.revision !== args.revision)) throw 'Revision conflict';
      const note = {...args.note,id:args.id || nextId++,revision:(current?.revision || 0)+1,updated_at:new Date().toISOString()};
      window.qaNotes = [note,...window.qaNotes.filter(item=>item.id !== note.id)];
      return structuredClone(note);
    }
    if (cmd === 'delete_note') { window.qaNotes = window.qaNotes.filter(note=>note.id !== args.id); return; }
    if (cmd === 'set_island_expanded') { if(window.qaLayoutDelay) await new Promise(resolve=>setTimeout(resolve,window.qaLayoutDelay)); return args.expanded ? args.calendar ? [innerWidth,innerHeight] : [760,520] : [480,196]; }
    if (cmd === 'exit_app') return;
    if (cmd === 'create_task') {
      const task = { ...base, id: nextId++, ...args.task };
      if(task.due_at && !task.reminder_at) task.reminder_at = new Date(Date.parse(task.due_at)-1800000).toISOString();
      window.qaTasks.push(task);
      return structuredClone(task);
    }
    const task = window.qaTasks.find(task => task.id === args.id);
    if (!task) throw 'Task not found';
    if (cmd === 'complete_task') task.status = args.completed ? 'done' : 'open';
    else if (cmd === 'update_task') Object.assign(task, args.patch);
    else if (cmd === 'reschedule_task') { task.due_at = args.dueAt; task.reminder_at = args.reminderAt || null; }
    else if (cmd === 'delete_task') window.qaTasks = window.qaTasks.filter(task => task.id !== args.id);
    else throw `Unmocked command ${cmd}`;
    return structuredClone(task);
  }, transformCallback: callback => { const id = ++callbackId; callbacks.set(id, callback); return id; } };
})();
