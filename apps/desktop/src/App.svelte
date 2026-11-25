<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { Bell, CalendarDays, Check, ChevronDown, Clock3, Flag, ListTodo, House,
    Pause, Pencil, Pin, Play, Plus, Power, RotateCcw, SlidersHorizontal, Trash2, X, Clipboard, Music2, CloudSun, SkipBack, SkipForward, NotebookPen } from 'lucide-svelte';
  import { createLiquidIsland, type AudioFrame } from './lib/liquid';
  import PlayerVolume from './lib/PlayerVolume.svelte';
  import SelectionToolbar from './lib/SelectionToolbar.svelte';
  import FormattedInput from './lib/FormattedInput.svelte';
  import FormattedText from './lib/FormattedText.svelte';
  import TimerDuration from './lib/TimerDuration.svelte';
  import WidgetPreferences from './lib/WidgetPreferences.svelte';
  import { defaultWidgetSettings } from './lib/widget-settings';
  import CalendarPanel from './lib/CalendarPanel.svelte';
  import ClipboardPanel from './lib/ClipboardPanel.svelte';
  import MusicPanel from './lib/MusicPanel.svelte';
  import WeatherPanel from './lib/WeatherPanel.svelte';
  import WeatherIcon from './lib/WeatherIcon.svelte';
  import QuickReminder from './lib/QuickReminder.svelte';
  import HomePanel from './lib/HomePanel.svelte';
  import ReminderNotice from './lib/ReminderNotice.svelte';
  import ReminderReview from './lib/ReminderReview.svelte';
  import { reminderReview } from './lib/reminder-review';
  import AppearancePicker from './lib/AppearancePicker.svelte';
  import CapriFace from './lib/CapriFace.svelte';
  import { loadAppearance, saveAppearance, type IslandAppearance } from './lib/appearance';
  import { degrees, weatherLabel } from './lib/weather';
  import { createPresence } from './lib/presence';
  import type { MediaState, NewTask, Task, WeatherState, WidgetSettings } from './types';

  type Tab = 'home' | 'today' | 'tasks' | 'calendar' | 'done' | 'clipboard' | 'music' | 'weather' | 'notes';
  const tabs: { id: Tab; label: string; icon: typeof ListTodo }[] = [
    { id: 'home', label: 'Главная', icon: House },
    { id: 'today', label: 'Сегодня', icon: Clock3 },
    { id: 'tasks', label: 'Задачи', icon: ListTodo },
    { id: 'calendar', label: 'Календарь', icon: CalendarDays },
    { id: 'notes', label: 'Заметки', icon: NotebookPen },
    { id: 'music', label: 'Музыка', icon: Music2 },
    { id: 'weather', label: 'Погода', icon: CloudSun },
    { id: 'clipboard', label: 'Буфер обмена', icon: Clipboard },
    { id: 'done', label: 'Готово', icon: Check },
  ];
  let tasks: Task[] = [];
  let expanded = false;
  let panelWidth = 704;
  let panelHeight = 458;
  let layoutBusy = false;
  let queuedTab:Tab | null = null;
  let calendarBusy = false;
  let calendarPlanner = false;
  let taskFilter:'all' | 'dated' | 'undated' = 'all';
  let visible = false;
  let activeGeneration = 0;
  let presentationVersion = 0;
  let dismissing = false;
  let forceHiding = false;
  let revealUntil = 0;
  let nativeOutsideSince = 0;
  let shortcutEditing = false;
  let shortcutReady = false;
  let automaticPaste = true;
  let shortcutMode: import('./lib/widget-settings').ShortcutMode = 'windows';
  const REVEAL_MS = 5_000;
  const TRACK_REVEAL_MS = 3_000;
  let tab: Tab = 'home';
  let showForm = false;
  let notesPanel: { flush: () => Promise<boolean> } | undefined;
  let title = '';
  let dateTime = '';
  let notes = '';
  let priority = 0;
  let busy = false;
  let error = '';
  let refreshError = '';
  let editId: number | null = null;
  let editDate = '';
  let deleteId: number | null = null;
  let now = new Date();
  let selectedDate = new Date();
  let hovered = false;
  let nativeHovered: boolean | null = null;
  let pinned = false;
  let settingsOpen = false;
  let widgetSettings: WidgetSettings = defaultWidgetSettings;
  let settingsBusy = false;
  let settingsError = '';
  let liquidEnabled = true;
  let equalizerEnabled = true;
  let appearance: IslandAppearance = 'island';
  let appearanceError = '';
  let reducedMotion = false;
  let transition = 0;
  let announcement = '';
  let collapseTimer: ReturnType<typeof setTimeout> | undefined;
  let announceTimer: ReturnType<typeof setTimeout> | undefined;
  let revealTimer: ReturnType<typeof setTimeout> | undefined;
  let canvas: HTMLCanvasElement;
  let shell: HTMLDivElement;
  let interaction: HTMLDivElement;
  let titleInput: HTMLInputElement;
  let liquid: ReturnType<typeof createLiquidIsland> | undefined;
  let presence: ReturnType<typeof createPresence> | undefined;
  let media: MediaState | null = null;
  let mediaError = '';
  let preferredMedia: string | null = null;
  let mediaRequest = 0;
  let mediaLoading = false;
  let lastMediaEvent = 0;
  let compactMode: 'manual' | 'track' | 'reminder' = 'manual';
  let reminderQueue: Task[] = [];
  let activeReminder: Task | null = null;
  let reminderPhase: 'bell' | 'opening' | 'message' = 'bell';
  let reminderUntil = 0;
  let reminderDeferredUntil = 0;
  let reminderBusy = false;
  let reminderClosing = false;
  let reminderHovered = false;
  let reminderAcked = false;
  let reminderAckBusy = false;
  let reminderVersion = 0;
  let reviewActive = false;
  let reviewIndex = 0;
  let reviewNextAt = 0;
  let reviewLeaseExtended = false;
  const reviewAcknowledging = new Set<string>();
  let highlightedTask: number | null = null;
  let highlightTimer: ReturnType<typeof setTimeout> | undefined;
  const seenReminders = new Set<string>();
  const reminderKey = (task: Task) => `${task.id}:${task.reminder_at}`;
  let volumeOpen = false;
  let coverVolumeOpen = false;
  let mediaBusy = false;
  let viewStage:HTMLDivElement;
  let viewAnimation:Animation | undefined;
  let overlayRequested = false;
  let overlayGeneration = 0;
  let overlayTimer:ReturnType<typeof setTimeout> | undefined;
  $: compactPlayback = !!media?.session_id && !!media.title.trim();
  $: musicPeek = compactMode === 'track' && compactPlayback;
  $: reviewItems = reminderReview(tasks, now);
  $: reviewedTask = reviewActive && reviewItems.length ? reviewItems[reviewIndex % reviewItems.length] : null;
  $: if (reviewedTask && visible && !expanded && !dismissing) {
    extendReviewLease(reviewItems.length);
    void acknowledgeReview(reviewedTask, activeGeneration);
  }
  $: capriMode = appearance === 'portrait' && compactMode === 'manual' && !activeReminder && !reviewedTask;
  $: capriCompact = capriMode && !expanded;
  $: compactWidth = capriMode ? 272 : compactMode === 'reminder' ? reminderPhase === 'bell' ? 96 : 272 : compactMode === 'manual' ? 272 : 360;
  $: compactHeight = capriMode ? 104 : compactMode === 'reminder' ? reminderPhase === 'bell' ? 40 : 56 : compactMode === 'manual' ? 56 : 76;
  $: if (liquid && !expanded) liquid.setCompact(compactWidth, compactHeight);
  $: overlayNeeded = visible && !expanded && compactPlayback && (coverVolumeOpen || (musicPeek && volumeOpen));
  $: if (overlayNeeded !== overlayRequested || overlayGeneration !== activeGeneration) {
    overlayRequested = overlayNeeded; overlayGeneration = activeGeneration;
    updateOverlay(overlayNeeded, activeGeneration);
  }
  function updateOverlay(open:boolean, generation:number) {
    clearTimeout(overlayTimer);
    const send = () => { void invoke('set_island_overlay',{open,generation}).catch(err => mediaError = String(err)); };
    if (open || reducedMotion) send();
    else overlayTimer = setTimeout(send,200);
  }
  async function animateView() {
    await tick();
    if (!viewStage || reducedMotion || !expanded) return;
    const opacity = viewAnimation?.playState === 'running' ? Math.max(.4,Number(getComputedStyle(viewStage).opacity)) : 0;
    viewAnimation?.cancel();
    viewAnimation = viewStage.animate([{opacity,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:280,easing:'cubic-bezier(.22,1,.36,1)'});
  }
  async function compactCommand(action: string) {
    if (!media?.session_id || mediaBusy) return false;
    mediaBusy = true;
    try {
      await invoke('media_command', { sessionId: media.session_id, action }); await refreshMedia();
      return true;
    }
    catch (err) { mediaError = String(err); return false; }
    finally { mediaBusy = false; }
  }
  async function playFromHome() {
    if (mediaBusy) return;
    mediaError = '';
    if (media?.session_id && media.can_toggle && await compactCommand('toggle')) return;
    mediaError = '';
    mediaBusy = true;
    try {
      const playing = await invoke<MediaState>('start_yandex_music');
      mediaRequest++;
      preferredMedia = playing.session_id;
      media = playing;
      lastMediaEvent = Date.now();
    } catch (err) { mediaError = String(err); }
    finally { mediaBusy = false; }
  }
  let weather: WeatherState = { data: null, stale: false, error: null };
  let weatherLoading = false;
  let weatherRequest = 0;
  let focusMinutes = 25;
  let focusSeconds = focusMinutes * 60;
  let focusTotalSeconds = focusSeconds;
  let timerRunning = false;
  let timerEndsAt = 0;

  const toLocalInput = (value?: string | null) => {
    if (!value) return '';
    const date = new Date(value);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  };
  const dayEnd = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);
  const dateLabel = (value: string) => {
    const date = new Date(value);
    return `${date.toDateString() === now.toDateString() ? 'Сегодня' : date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}, ${date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`;
  };
  const overdue = (task: Task) => !!task.due_at && new Date(task.due_at) < now && task.status === 'open';
  const countdown = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
  const taskPlural = new Intl.PluralRules('ru');
  const taskWord = (count: number) => {
    const form = taskPlural.select(count);
    return form === 'one' ? 'задача' : form === 'few' ? 'задачи' : 'задач';
  };
  $: openTasks = tasks.filter(task => task.status === 'open');
  $: todayTasks = openTasks.filter(task => task.due_at && new Date(task.due_at) < dayEnd(now));
  $: datedTasks = openTasks.filter(task => task.due_at);
  $: undatedTasks = openTasks.filter(task => !task.due_at);
  $: doneTasks = tasks.filter(task => task.status === 'done');
  $: filteredTasks = tab === 'today' ? todayTasks : tab === 'tasks' ? taskFilter === 'dated' ? datedTasks : taskFilter === 'undated' ? undatedTasks : openTasks : doneTasks;
  $: reminders = openTasks.filter(task => task.due_at).sort((a,b) => Date.parse(a.due_at!) - Date.parse(b.due_at!)).slice(0, 3);
  $: nextTask = reminders[0] || openTasks[0];
  $: tabTitle = tab === 'today' ? 'Сегодня' : tab === 'tasks' ? 'Задачи' : 'Готово';
  $: timerProgress = Math.min(1, focusSeconds / focusTotalSeconds);
  let nativeAudioEnabled = false;
  async function syncAudio(enabled: boolean) {
    if (nativeAudioEnabled === enabled) return;
    nativeAudioEnabled = enabled;
    try { await invoke('set_audio_reactivity', {enabled}); }
    catch { nativeAudioEnabled = false; }
  }
  $: audioActive = shortcutReady && visible && !!media?.playing && equalizerEnabled && !capriCompact && !reducedMotion;
  $: if (shortcutReady) void syncAudio(audioActive);
  $: if (liquid) liquid.configure(reducedMotion, liquidEnabled && !capriCompact, visible && !!media?.playing, visible, equalizerEnabled && !capriCompact);
  $: if (liquid) liquid.setPalette(appearance === 'portrait' ? '#080f0d' : '#000', appearance === 'portrait' ? '#32835a' : '#292929');

  let taskRequest = 0;
  async function refresh() {
    const request = ++taskRequest;
    try {
      const latest = await invoke<Task[]>('list_tasks', { includeCompleted: true });
      if (request === taskRequest) { tasks = latest; refreshError = ''; }
    } catch (err) { if (request === taskRequest) refreshError = String(err); }
  }

  function extendReviewLease(count: number) {
    if (reviewLeaseExtended) return;
    reviewLeaseExtended = true;
    revealUntil = Date.now() + Math.max(8_000, Math.min(count, 3) * 4_500 + 1_500);
    clearTimeout(revealTimer);
    revealTimer = setTimeout(() => { if (canAutoHide()) void hideIsland(); }, revealUntil - Date.now());
  }
  function nextReview(manual = false) {
    if (!reviewItems.length) return;
    reviewIndex = (reviewIndex + 1) % reviewItems.length;
    reviewNextAt = Date.now() + 4_500;
    if (manual) {
      revealUntil = Math.max(revealUntil, Date.now() + 5_000);
      clearTimeout(revealTimer);
      revealTimer = setTimeout(() => { if (canAutoHide()) void hideIsland(); }, revealUntil - Date.now());
    }
  }
  async function acknowledgeReview(task: Task, generation: number) {
    if (!task.reminder_at || Date.parse(task.reminder_at) > Date.now() || task.notification_sent_at) return;
    const key = reminderKey(task);
    if (seenReminders.has(key) || reviewAcknowledging.has(key)) return;
    reviewAcknowledging.add(key);
    try {
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (!reviewActive || !visible || dismissing || expanded || activeGeneration !== generation || reviewedTask?.id !== task.id) return;
      const delivered = await invoke<boolean>('acknowledge_island_review', {id:task.id,reminderAt:task.reminder_at,generation});
      if (delivered) {
        seenReminders.add(key);
        reminderQueue = reminderQueue.filter(item => reminderKey(item) !== key);
      }
    } catch { /* The next visible review retries; tasks never become completed here. */ }
    finally { reviewAcknowledging.delete(key); }
  }
  async function openReviewedTask() {
    const task = reviewedTask;
    if (!task) return;
    reviewActive = false; tab = 'tasks'; taskFilter = 'all';
    showForm = false; editId = null; deleteId = null;
    await openDashboard(); await refresh(); await tick();
    highlightedTask = task.id;
    await tick();
    document.querySelector(`[data-task-id="${task.id}"]`)?.scrollIntoView({block:'nearest'});
    clearTimeout(highlightTimer);
    highlightTimer = setTimeout(() => highlightedTask = null, 4_000);
  }
  async function refreshMedia() {
    if (mediaLoading) return;
    const version = ++mediaRequest;
    mediaLoading = true;
    try {
      const result = await invoke<MediaState>('get_media_state', { preferred: preferredMedia });
      if (version === mediaRequest) { media = result; mediaError = ''; }
    } catch (err) { if (version === mediaRequest) mediaError = String(err); }
    finally { if (version === mediaRequest) mediaLoading = false; }
  }
  async function refreshWeather() {
    if (weatherLoading) return;
    weatherLoading = true;
    const version = ++weatherRequest;
    try {
      const result = await invoke<WeatherState>('get_weather');
      if (version === weatherRequest) weather = result;
    } catch (err) {
      if (version === weatherRequest) weather = { ...weather, stale: !!weather.data, error: String(err) };
    } finally { if (version === weatherRequest) weatherLoading = false; }
  }
  async function pasteClipboard(id: number) {
    busy = true;
    try {
      const automatic = await invoke<boolean>('copy_clipboard_entry', { id });
      automaticPaste = automatic;
      await hideIsland(true);
      if (automatic) await invoke('paste_to_previous_window');
    } catch (err) {
      visible = true;
      await openDashboard();
      await tick();
      void presence?.show();
      throw err;
    } finally { busy = false; }
  }
  async function setExpanded(value: boolean) {
    clearTimeout(collapseTimer);
    const version = ++transition;
    if (expanded === value) return;
    if (value) {
      try {
        const wide = tab === 'calendar' && calendarPlanner;
        const size = await invoke<[number,number] | undefined>('set_island_expanded', { expanded: true, generation: activeGeneration, calendar: wide });
        if (version !== transition) return;
        setPanelSize(size || (wide ? [1280,820] : [760,520]));
        expanded = true; await liquid?.setExpanded(true);
      } catch (err) { error = String(err); }
    } else {
      expanded = false; settingsOpen = false;
      await liquid?.setExpanded(false);
      if (version !== transition) return;
      try { await invoke('set_island_expanded', { expanded: false, generation: activeGeneration }); }
      catch (err) { error = String(err); }
    }
  }
  function pointerEnter() {
    if (!visible) return;
    hovered = true; nativeHovered = null; clearTimeout(collapseTimer); clearTimeout(revealTimer);
    if (dismissing && !forceHiding) void openDashboard();
  }
  function pointerLeave() {
    hovered = false; nativeHovered = null; liquid?.leave();
    if (!visible) return;
    clearTimeout(collapseTimer);
    collapseTimer = setTimeout(() => {
      if (canAutoHide()) void hideIsland();
    }, Math.max(650, revealUntil - Date.now()));
  }
  function canAutoHide() {
    return !activeReminder && !reminderBusy && !reminderClosing && !showForm && editId === null && deleteId === null && !busy && !mediaBusy && !layoutBusy && !calendarBusy && !(nativeHovered ?? hovered) && !pinned && !settingsOpen && !shortcutEditing;
  }
  function receiveReminders(incoming: Task[]) {
    for (const task of incoming) {
      if (!task.reminder_at || seenReminders.has(reminderKey(task))) continue;
      if (activeReminder && reminderKey(activeReminder) === reminderKey(task)) {
        if (!reminderAcked) void acknowledgeReminder(activeReminder, activeGeneration);
        continue;
      }
      if (!reminderQueue.some(queued => reminderKey(queued) === reminderKey(task))) reminderQueue = [...reminderQueue, task];
    }
    void presentNextReminder();
  }
  async function acknowledgeReminder(task: Task, generation: number) {
    if (reminderAckBusy || reminderPhase !== 'message' || !task.reminder_at) return;
    reminderAckBusy = true;
    try {
      const delivered = await invoke<boolean>('acknowledge_island_reminder', {id:task.id, reminderAt:task.reminder_at, generation});
      if (!activeReminder || reminderKey(activeReminder) !== reminderKey(task) || activeGeneration !== generation) return;
      if (!delivered) { void dismissReminder(); return; }
      reminderAcked = true;
      seenReminders.add(reminderKey(task));
      if (seenReminders.size > 512) seenReminders.delete(seenReminders.values().next().value!);
    } catch { /* Keep it pending in SQLite; the next scheduler event retries acknowledgement. */ }
    finally { reminderAckBusy = false; }
  }
  async function presentNextReminder() {
    if (reviewActive || activeReminder || reminderBusy || reminderClosing || dismissing || layoutBusy || calendarBusy || !reminderQueue.length || Date.now() < reminderDeferredUntil) return;
    reminderBusy = true;
    const candidate = reminderQueue[0];
    reminderQueue = reminderQueue.slice(1);
    const version = ++reminderVersion;
    try {
      const latest = await invoke<Task[]>('list_tasks', {includeCompleted:true});
      const task = latest.find(item => item.id === candidate.id && item.status === 'open' && !item.notification_sent_at
        && item.reminder_at === candidate.reminder_at && Date.parse(item.reminder_at!) <= Date.now());
      if (!task || version !== reminderVersion) return;
      const presentation = await invoke<{generation:number;expanded:boolean}>('show_reminder_island', {generation:activeGeneration});
      if (version !== reminderVersion) return;
      const animateIn = !visible || dismissing;
      activeGeneration = presentation.generation;
      activeReminder = task; reminderAcked = false; reminderHovered = false;
      reminderPhase = reducedMotion ? 'message' : 'bell';
      reminderUntil = Infinity;
      tasks = latest;
      visible = true; dismissing = false; forceHiding = false;
      if (!presentation.expanded) {
        compactMode = 'reminder'; volumeOpen = false; coverVolumeOpen = false;
        nativeHovered = null; hovered = false;
        clearTimeout(revealTimer); clearTimeout(collapseTimer);
        await setExpanded(false);
      }
      await tick();
      if (version !== reminderVersion) return;
      if (animateIn) void presence?.show();
      if (!reducedMotion) {
        // Bell strike, shape expansion, then content. A newer presentation
        // cancels the remaining choreography without consuming the reminder.
        await new Promise(resolve => setTimeout(resolve, 1_000));
        if (version !== reminderVersion) return;
        reminderPhase = 'opening';
        await new Promise(resolve => setTimeout(resolve, 420));
        if (version !== reminderVersion) return;
        reminderPhase = 'message';
        await tick();
      }
      // Do not consume a due reminder until the actual island has painted it.
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (version === reminderVersion && activeReminder) {
        reminderUntil = Date.now() + 8_000;
        await acknowledgeReminder(task, activeGeneration);
      }
    } catch {
      if (!seenReminders.has(reminderKey(candidate))) reminderQueue = [candidate, ...reminderQueue];
      reminderDeferredUntil = Date.now() + 1_000;
    } finally { reminderBusy = false; }
  }
  function expireReminder() {
    const held = expanded ? reminderHovered : (nativeHovered ?? hovered);
    if (activeReminder && !reminderBusy && !reminderClosing && Date.now() >= reminderUntil && !held) void dismissReminder();
  }
  async function dismissReminder(openTask = false) {
    if (!activeReminder || reminderClosing) return;
    reminderClosing = true;
    const task = activeReminder;
    const generation = activeGeneration;
    // Clicking Close/Open itself proves that the reminder reached the screen,
    // including a click before the initial paint acknowledgement completes.
    if (!reminderAcked) await acknowledgeReminder(task, generation);
    reminderVersion++;
    try {
      if (!reducedMotion && (expanded || reminderQueue.length)) await new Promise(resolve => setTimeout(resolve, 180));
      if (!expanded && !openTask && !reminderQueue.length) await hideIsland(true);
      activeReminder = null; reminderAcked = false; reminderHovered = false;
      await invoke('finish_island_reminder', {generation});
      if (openTask) {
        compactMode = 'manual'; tab = 'tasks'; taskFilter = 'all';
        showForm = false; editId = null; deleteId = null;
        revealUntil = Date.now() + REVEAL_MS; nativeOutsideSince = Date.now();
        await openDashboard(); await refresh(); await tick();
        highlightedTask = task.id;
        await tick();
        document.querySelector(`[data-task-id="${task.id}"]`)?.scrollIntoView({block:'nearest',behavior:reducedMotion ? 'instant' : 'smooth'});
        clearTimeout(highlightTimer); highlightTimer = setTimeout(() => highlightedTask = null, 3500);
      } else if (!expanded && !reminderQueue.length) compactMode = 'manual';
    } finally { reminderClosing = false; }
    void presentNextReminder();
  }
  function nativePointer(inside: boolean) {
    liquid?.flushOverdueTransition();
    presence?.flush();
    if (!visible || dismissing) return;
    const wasInside = nativeHovered === true;
    nativeHovered = inside;
    expireReminder();
    if (inside) { nativeOutsideSince = 0; return; }
    if (wasInside || !nativeOutsideSince) nativeOutsideSince = Date.now();
    if (Date.now() >= revealUntil && Date.now() - nativeOutsideSince >= 650 && canAutoHide()) void hideIsland();
  }
  async function toggleFromShortcut() {
    if (visible && !dismissing) {
      await hideIsland(true);
    } else {
      try { await invoke('reveal_island_shortcut'); }
      catch (err) { error = String(err); }
    }
  }
  async function revealFromShortcut(payload: number | {generation: number; reason: 'manual' | 'track' | 'hourly' | 'startup'}) {
    if (activeReminder && typeof payload !== 'number' && payload.reason !== 'manual') return;
    if (reviewActive && visible && !dismissing && typeof payload !== 'number' && payload.reason === 'track') return;
    reminderVersion++;
    activeReminder = null; reminderAcked = false; reminderHovered = false;
    reminderDeferredUntil = Date.now() + REVEAL_MS;
    const generation = typeof payload === 'number' ? payload : payload.generation;
    compactMode = typeof payload !== 'number' && payload.reason === 'track' ? 'track' : 'manual';
    reviewActive = typeof payload !== 'number' && (payload.reason === 'startup' || payload.reason === 'hourly');
    reviewIndex = 0; reviewNextAt = Date.now() + 4_500; reviewLeaseExtended = false;
    volumeOpen = false; coverVolumeOpen = false;
    const animateIn = !visible || dismissing;
    const version = ++presentationVersion;
    dismissing = false;
    forceHiding = false;
    activeGeneration = generation;
    nativeHovered = null;
    visible = true;
    now = new Date();
    void refresh();
    void refreshMedia();
    void refreshWeather();
    revealUntil = Date.now() + (compactMode === 'track' ? TRACK_REVEAL_MS : REVEAL_MS);
    nativeOutsideSince = Date.now();
    clearTimeout(revealTimer); clearTimeout(collapseTimer);
    showForm = false; editId = null; deleteId = null; pinned = false;
    await setExpanded(false);
    if (version !== presentationVersion) return;
    calendarPlanner = false;
    await tick();
    if (version !== presentationVersion) return;
    if (animateIn) void presence?.show();
    // Resize/show can place the panel under an already stationary cursor.
    hovered = interaction.matches(':hover');
    const remaining = Math.max(0, revealUntil - Date.now());
    revealTimer = setTimeout(() => { if (canAutoHide()) void hideIsland(); }, remaining);
  }
  async function openDashboard() {
    reviewActive = false;
    volumeOpen = false; coverVolumeOpen = false;
    if (dismissing) void presence?.show();
    ++presentationVersion;
    dismissing = false;
    clearTimeout(collapseTimer);
    await setExpanded(true);
  }
  async function selectTab(value: Tab) {
    if (layoutBusy) { queuedTab = value; return; }
    if (tab === 'notes' && notesPanel && !await notesPanel.flush()) return;
    if (value === tab) return;
    const resize = expanded && tab === 'calendar' && calendarPlanner;
    tab = value; editId = null; deleteId = null;
    calendarPlanner = false;
    if (resize) await resizeDashboard(false);
    void animateView();
  }
  async function changeCalendarLayout(wide:boolean) {
    if (layoutBusy || tab !== 'calendar' || calendarPlanner === wide) return;
    calendarPlanner = wide;
    if (expanded) await resizeDashboard(wide);
  }
  async function resizeDashboard(wide:boolean) {
      layoutBusy = true;
      const version = ++transition;
      try {
        if (!wide) { setPanelSize([760,520]); await liquid?.setExpanded(true); }
        if (version !== transition) return;
        const size = await invoke<[number,number] | undefined>('set_island_expanded',{expanded:true,generation:activeGeneration,calendar:wide});
        if (version !== transition) return;
        setPanelSize(size || (wide ? [1280,820] : [760,520]));
        await liquid?.setExpanded(true);
      } catch (err) { error = String(err); }
      finally { layoutBusy = false; if (queuedTab) { const next = queuedTab; queuedTab = null; void selectTab(next); } }
  }
  function setPanelSize(size:[number,number]) { panelWidth = size[0]-56; panelHeight = size[1]-62; liquid?.setExpandedSize(panelWidth,panelHeight); }
  async function hideIsland(force = false) {
    if (dismissing || !visible) return;
    reviewActive = false;
    dismissing = true;
    forceHiding = force;
    const version = ++presentationVersion;
    const generation = activeGeneration;
    clearTimeout(revealTimer); clearTimeout(collapseTimer);
    volumeOpen = false; coverVolumeOpen = false;
    await Promise.all([setExpanded(false), presence?.hide()]);
    if (version !== presentationVersion) return;
    visible = false; hovered = false;
    try { await invoke('hide_island', { generation }); }
    catch (err) { error = String(err); visible = true; }
    finally { if (version === presentationVersion) { dismissing = false; forceHiding = false; } }
    if (!visible) {
      calendarPlanner = false; presence?.reset();
      // A forced close or clipboard paste can hide the expanded panel while
      // its inline reminder is present. Release that presentation as well.
      if (activeReminder && !reminderClosing) {
        reminderVersion++;
        activeReminder = null; reminderAcked = false; reminderHovered = false;
        compactMode = 'manual';
        await invoke('finish_island_reminder', {generation});
      }
    }
  }
  function collapse() {
    if (activeReminder && !expanded) { void dismissReminder(); return; }
    showForm = false; editId = null; deleteId = null; void hideIsland(true);
  }
  async function syncShortcutEditing() {
    await tick();
    const editing = document.hasFocus() && !!(document.activeElement?.matches('input, textarea, select, [contenteditable="true"]') || document.activeElement?.closest('.selection-toolbar'));
    if (editing === shortcutEditing) return;
    shortcutEditing = editing;
    try { await invoke('set_island_shortcut_editing', { editing }); }
    catch (err) { error = String(err); }
  }
  function announce(message: string) {
    announcement = message; liquid?.celebrate(); clearTimeout(announceTimer);
    announceTimer = setTimeout(() => announcement = '', 3200);
  }
  function updateAppearance(style: IslandAppearance, liquid = liquidEnabled, equalizer = equalizerEnabled) {
    appearance = style;
    liquidEnabled = liquid;
    equalizerEnabled = equalizer;
    appearanceError = saveAppearance({style, liquid, equalizer}) ? '' : 'Не удалось сохранить оформление. Оно действует до перезапуска.';
    void invoke('set_island_appearance', {portrait:style === 'portrait'}).catch(() => {
      appearanceError = 'Не удалось применить оформление. Попробуй выбрать его ещё раз.';
    });
  }
  async function saveWidgetSettings(settings: WidgetSettings): Promise<boolean> {
    if (settingsBusy) return false;
    settingsBusy = true; settingsError = '';
    try { widgetSettings = await invoke<WidgetSettings>('set_widget_settings', {settings}); return true; }
    catch (err) { settingsError = String(err); return false; }
    finally { settingsBusy = false; }
  }
  async function openComposer() {
    if (tab === 'home') tab = 'tasks';
    clearTimeout(collapseTimer); showForm = true; editId = null; deleteId = null;
    if (tab === 'calendar' && !dateTime) {
      const date = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate(), 18);
      dateTime = toLocalInput(date.toISOString());
    }
    await tick(); titleInput?.focus();
  }
  async function saveTask() {
    if (!title.trim() || busy) return;
    busy = true; error = '';
    try {
      const task: NewTask = { title: title.trim(), notes: notes.trim() || null, priority,
        due_at: dateTime ? new Date(dateTime).toISOString() : null };
      await invoke('create_task', { task });
      title = ''; dateTime = ''; notes = ''; priority = 0; showForm = false;
      await refresh();
      taskFilter = 'all';
      tab = task.due_at && new Date(task.due_at) < dayEnd(now) ? 'today' : 'tasks';
      announce('Задача добавлена');
    } catch (err) { error = String(err); }
    finally { busy = false; }
  }
  async function toggleDone(task: Task) {
    error = '';
    try {
      await invoke('complete_task', { id: task.id, completed: task.status !== 'done' });
      await refresh(); if (task.status !== 'done') announce('Задача завершена');
    } catch (err) { error = String(err); }
  }
  async function cyclePriority(task: Task) {
    error = '';
    try {
      await invoke('update_task', { id: task.id, patch: { priority: (task.priority + 1) % 3 } }); await refresh();
    } catch (err) { error = String(err); }
  }
  async function removeTask(task: Task) {
    error = '';
    try { await invoke('delete_task', { id: task.id }); deleteId = null; await refresh(); }
    catch (err) { error = String(err); }
  }
  function startEditing(task: Task) { editId = task.id; editDate = toLocalInput(task.due_at); deleteId = null; }
  async function saveEdit(task: Task) {
    error = '';
    try {
      await invoke('reschedule_task', { id: task.id, dueAt: editDate ? new Date(editDate).toISOString() : null, reminderAt: null });
      editId = null; await refresh();
    } catch (err) { error = String(err); }
  }
  async function exitApp() { try { if (notesPanel && !await notesPanel.flush()) return; await invoke('exit_app'); } catch (err) { error = String(err); } }
  function setFocusMinutes(minutes: number) {
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 240) return;
    focusMinutes = minutes; focusSeconds = minutes * 60; focusTotalSeconds = focusSeconds; timerRunning = false;
    try { localStorage.setItem('personal-island.focus-minutes.v1', String(minutes)); } catch { /* Current timer still works. */ }
  }
  function addFocusMinutes(minutes: number) {
    if (!Number.isInteger(minutes) || minutes < 1 || focusTotalSeconds + minutes * 60 > 4 * 3600) return;
    focusSeconds = (timerRunning ? Math.max(0,Math.ceil((timerEndsAt-Date.now())/1000)) : focusSeconds) + minutes * 60;
    focusTotalSeconds += minutes * 60;
    if (timerRunning) timerEndsAt += minutes * 60000;
  }
  function addFocusMinute() { addFocusMinutes(1); }
  function toggleTimer() {
    if (timerRunning) {
      focusSeconds = Math.max(0, Math.ceil((timerEndsAt - Date.now()) / 1000)); timerRunning = false;
    } else {
      if (!focusSeconds) { focusSeconds = focusMinutes * 60; focusTotalSeconds = focusSeconds; }
      timerEndsAt = Date.now() + focusSeconds * 1000; timerRunning = true;
    }
  }
  function keydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      if (volumeOpen || coverVolumeOpen) { volumeOpen = false; coverVolumeOpen = false; return; }
      if (tab === 'calendar' && calendarBusy) return;
      if (tab === 'calendar' && calendarPlanner) { void changeCalendarLayout(false); return; }
      if (settingsOpen) settingsOpen = false;
      else if (showForm) showForm = false;
      else if (editId !== null || deleteId !== null) { editId = null; deleteId = null; }
      else collapse();
    }
  }
  onMount(() => {
    void invoke<{automaticPaste: boolean; shortcutMode?: typeof shortcutMode}>('get_platform_capabilities')
      .then(capabilities => {
        automaticPaste = capabilities.automaticPaste;
        shortcutMode = capabilities.shortcutMode ?? 'windows';
      })
      .catch(() => {});
    const appearanceSettings = loadAppearance();
    appearance = appearanceSettings.style;
    liquidEnabled = appearanceSettings.liquid;
    equalizerEnabled = appearanceSettings.equalizer;
    try {
      const savedMinutes = Number(localStorage.getItem('personal-island.focus-minutes.v1'));
      if (Number.isInteger(savedMinutes) && savedMinutes >= 1 && savedMinutes <= 240) setFocusMinutes(savedMinutes);
    } catch { /* Use the default duration when storage is unavailable. */ }
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    let unlistenPointer: UnlistenFn | undefined;
    let unlistenMedia: UnlistenFn | undefined;
    let unlistenReminders: UnlistenFn | undefined;
    let unlistenAudio: UnlistenFn | undefined;
    const motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
    reducedMotion = motionQuery.matches;
    presence = createPresence(shell, () => reducedMotion);
    const motionChange = () => reducedMotion = motionQuery.matches;
    motionQuery.addEventListener('change', motionChange);
    liquid = createLiquidIsland(canvas, { reducedMotion, liquid: liquidEnabled,
      onSize(width, height) {
        shell.style.setProperty('--shape-width', `${width}px`); shell.style.setProperty('--shape-height', `${height}px`);
        interaction.style.width = `${width + 48}px`; interaction.style.height = `${height + (expanded ? 28 : 64)}px`;
      },
    });
    refresh();
    void refreshWeather();
    void (async () => {
      try {
        const stopAudio = await listen<AudioFrame>('island-audio', event => liquid?.setAudio(event.payload));
        if (disposed) { stopAudio(); return; }
        unlistenAudio = stopAudio;
        const stopPointer = await listen<boolean>('island-pointer', event => nativePointer(event.payload));
        if (disposed) { stopPointer(); return; }
        unlistenPointer = stopPointer;
        const stopReminders = await listen<Task[]>('island-reminders', event => receiveReminders(event.payload));
        if (disposed) { stopReminders(); return; }
        unlistenReminders = stopReminders;
        unlistenMedia = await listen<MediaState>('media-changed', event => {
          lastMediaEvent = Date.now();
          // Native snapshots already use the selected source and fall back when
          // it closes. Accept that fallback so a paused cover cannot linger.
          mediaRequest++;
          mediaLoading = false;
          media = event.payload;
          mediaError = '';
          if (!media.session_id || !media.title.trim()) {
            volumeOpen = false; coverVolumeOpen = false;
            if (compactMode === 'track' && !expanded) compactMode = 'manual';
          }
        });
        const stop = await listen<number | {generation: number; reason: 'manual' | 'track' | 'hourly' | 'startup'}>('island-reveal', event => { void revealFromShortcut(event.payload); });
        if (disposed) { stop(); return; }
        unlisten = stop;
        const stopToggle = await listen('island-toggle', () => { void toggleFromShortcut(); });
        if (disposed) { stopToggle(); return; }
        const stopReveal = unlisten;
        unlisten = () => { stopReveal(); stopToggle(); };
        try { widgetSettings = await invoke<WidgetSettings>('get_widget_settings'); }
        catch (err) { settingsError = String(err); }
        await invoke('set_island_appearance', {portrait:appearance === 'portrait'});
        if (disposed) return;
        await invoke('register_island_shortcut');
        shortcutReady = true;
      } catch (err) {
        if (disposed) return;
        error = `Не удалось включить горячую клавишу: ${String(err)}`;
        visible = true;
        await setExpanded(true);
      }
    })();
    const reload = setInterval(() => { if (visible) void refresh(); }, 5_000);
    // Native events are authoritative; poll only to recover a missing event stream.
    const mediaPoll = setInterval(() => { if (visible && Date.now() - lastMediaEvent > 6_000) void refreshMedia(); }, 10_000);
    const weatherPoll = setInterval(() => { if (visible) void refreshWeather(); }, 60_000);
    const clock = setInterval(() => {
      now = new Date();
      expireReminder();
      if (reviewActive && visible && !expanded && Date.now() >= reviewNextAt && !(nativeHovered ?? hovered)) nextReview();
      if (!activeReminder) void presentNextReminder();
      if (timerRunning) {
        focusSeconds = Math.max(0, Math.ceil((timerEndsAt - Date.now()) / 1000));
        if (!focusSeconds) { timerRunning = false; announce('Время сделать перерыв'); }
      }
    }, 1_000);
    return () => {
      disposed = true; reminderVersion++; unlisten?.(); unlistenPointer?.(); unlistenMedia?.(); unlistenReminders?.(); unlistenAudio?.();
      void invoke('set_audio_reactivity', {enabled:false}).catch(() => {});
      transition++; presentationVersion++; taskRequest++; clearInterval(reload); clearInterval(clock);
      mediaRequest++; clearInterval(mediaPoll); presence?.reset();
      weatherRequest++; clearInterval(weatherPoll);
      clearTimeout(collapseTimer); clearTimeout(announceTimer); clearTimeout(revealTimer);
      clearTimeout(overlayTimer); viewAnimation?.cancel();
      clearTimeout(highlightTimer);
      motionQuery.removeEventListener('change', motionChange); liquid?.destroy();
    };
  });
</script>

<svelte:head><title>Personal Island</title><meta name="description" content="Задачи и время для фокуса — в одном островке." /></svelte:head>
<svelte:window on:keydown={keydown} on:focusin={syncShortcutEditing} on:focusout={syncShortcutEditing} on:focus={syncShortcutEditing} on:blur={syncShortcutEditing}/>

<div class="island-shell" class:expanded class:dismissing class:capri-compact={capriCompact} class:capri-theme={appearance === 'portrait'} class:concealed={!visible} aria-hidden={!visible} inert={!visible} data-shortcut-ready={shortcutReady} data-native-hover={nativeHovered} data-presentation={JSON.stringify({dismissing, revealUntil, nativeOutsideSince, showForm, editId, deleteId, busy, pinned, settingsOpen, shortcutEditing, activeGeneration, presentationVersion})} bind:this={shell}>
  <canvas class="liquid-surface" bind:this={canvas} aria-hidden="true"></canvas>
  <div class="island-interaction" bind:this={interaction} on:mouseenter={pointerEnter} on:mouseleave={pointerLeave}
    on:mousemove={event => liquid?.pointer(event.clientX, event.clientY)} role="presentation">
    <div class="compact-stage" class:invisible={expanded} class:wide={compactMode !== 'manual'} style:width={`${compactWidth}px`} style:height={`${compactHeight}px`} aria-hidden={expanded} inert={expanded}>
    {#if activeReminder}
      {#key reminderKey(activeReminder)}<ReminderNotice task={activeReminder} phase={reminderPhase} remaining={reminderQueue.length} leaving={reminderClosing} open={() => void dismissReminder(true)} dismiss={() => void dismissReminder()} hover={value => reminderHovered = value}/>{/key}
    {:else if reviewedTask}
      <ReminderReview task={reviewedTask} {now} count={reviewItems.length} index={reviewIndex % reviewItems.length} taskCount={openTasks.length} {weather} open={() => void openReviewedTask()} next={() => nextReview(true)}/>
    {:else if capriMode}
      <CapriFace {now} {focusSeconds} {timerRunning} tasksLabel={`${openTasks.length} ${taskWord(openTasks.length)}`} {weather} {media} playback={compactPlayback} {mediaBusy} {announcement} open={openDashboard} mediaCommand={compactCommand} bind:volumeOpen={coverVolumeOpen} {reducedMotion}/>
    {:else if musicPeek && media}
      <section class="track-peek" aria-label="Новый трек">
        <div class="track-peek-top"><PlayerVolume sessionId={media.session_id || ''} wheelOnly bind:open={coverVolumeOpen} onOpen={() => volumeOpen = false} detached detachedOffset={45} {reducedMotion}><button class="peek-art" aria-label="Открыть музыкальный плеер" title="Колёсико — громкость плеера" on:click={() => { tab = 'music'; void openDashboard(); }}>{#if media.artwork}<img class="pill-artwork" src={media.artwork} alt="Обложка текущего трека"/>{:else}<Music2 size={28}/>{/if}</button></PlayerVolume><button class="peek-title" on:click={() => { tab = 'music'; void openDashboard(); }}><b>{media.title || 'Без названия'}</b><span>{media.artist || media.source}</span></button>{#if media.session_id}<PlayerVolume sessionId={media.session_id} bind:open={volumeOpen} onOpen={() => coverVolumeOpen = false} detached detachedOffset={45} {reducedMotion}/>{/if}</div>
        <div class="peek-controls"><span>{media.source}</span><button aria-label="Предыдущий трек" disabled={mediaBusy || !media.can_previous} on:click={() => compactCommand('previous')}><SkipBack size={17} fill="currentColor"/></button><button aria-label={media.playing ? 'Приостановить музыку' : 'Продолжить музыку'} disabled={mediaBusy || !media.can_toggle} on:click={() => compactCommand('toggle')}>{#if media.playing}<Pause size={18} fill="currentColor"/>{:else}<Play size={18} fill="currentColor"/>{/if}</button><button aria-label="Следующий трек" disabled={mediaBusy || !media.can_next} on:click={() => compactCommand('next')}><SkipForward size={17} fill="currentColor"/></button></div>
        {#if mediaError}<small class="peek-error" role="alert">{mediaError}</small>{/if}
      </section>
    {:else if compactPlayback && media}
      <div class="pill music-pill" role="group" aria-label="Островок с управлением музыкой">
        <button class="pill-clock compact-open" aria-label="Развернуть список задач" on:click={openDashboard}>{now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}<small class:running={timerRunning}><Clock3 size={10}/>{countdown(focusSeconds)}</small></button>
        <div class="compact-playback">
          <button class="compact-skip" aria-label="Предыдущий трек" disabled={mediaBusy || !media.can_previous} on:click={() => compactCommand('previous')}><SkipBack size={13} fill="currentColor"/></button>
          <PlayerVolume sessionId={media.session_id || ''} wheelOnly bind:open={coverVolumeOpen} detached detachedOffset={14} {reducedMotion}>
          <button class="compact-cover" class:paused={!media.playing} aria-label={media.playing ? 'Приостановить музыку' : 'Продолжить музыку'} title={`${media.title || 'Без названия'} — ${media.artist || media.source} · Колёсико — громкость`} disabled={mediaBusy || !media.can_toggle} on:click={() => compactCommand('toggle')}>
            {#if media.artwork}<img class="pill-artwork" src={media.artwork} alt="Обложка текущего трека"/>{:else}<Music2 size={20}/>{/if}
            <span class="cover-action" aria-hidden="true">{#if media.playing}<Pause size={15} fill="currentColor"/>{:else}<Play size={15} fill="currentColor"/>{/if}</span>
          </button>
          </PlayerVolume>
          <button class="compact-skip" aria-label="Следующий трек" disabled={mediaBusy || !media.can_next} on:click={() => compactCommand('next')}><SkipForward size={13} fill="currentColor"/></button>
        </div>
        <button class="pill-details compact-open" aria-label="Открыть задачи и погоду" on:click={openDashboard}><span class="compact-task-count">{openTasks.length}{'\u00a0'}{taskWord(openTasks.length)}</span><span class="pill-weather" class:stale={weather.stale} title="Погода в Санкт-Петербурге">{#if weather.data}<WeatherIcon code={weather.data.current.weather_code} isDay={!!weather.data.current.is_day} size={12}/>{weather.stale ? '—°' : degrees(weather.data.current.temperature_2m)}{:else}<CloudSun size={12}/>—°{/if}</span></button>
      </div>
      {#if mediaError}<small class="compact-media-error" role="alert">{mediaError}</small>{/if}
    {:else}
      <button class="pill" aria-label="Развернуть список задач" on:click={openDashboard}>
        <span class="pill-clock">{now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}<small class:running={timerRunning}><Clock3 size={10}/>{countdown(focusSeconds)}</small></span>
        <span class="pill-summary">{#if announcement}<b>{announcement}</b>{:else}<b>{openTasks.length}<small>{'\u00a0'}{taskWord(openTasks.length)}</small></b>{/if}{#if media?.playing}<span class="pill-playing"><Music2 size={11} aria-hidden="true"/><span>Музыка</span></span>{:else}<small>осталось</small>{/if}</span>
        <span class="pill-details"><span class="pill-weather" class:stale={weather.stale} title="Погода в Санкт-Петербурге">{#if weather.data}<WeatherIcon code={weather.data.current.weather_code} isDay={!!weather.data.current.is_day} size={15}/>{weather.stale ? '—°' : degrees(weather.data.current.temperature_2m)}{:else}<CloudSun size={15}/>—°{/if}</span><small>СПб</small></span>
      </button>
    {/if}
    </div>
    <main class="dashboard" class:calendar-dashboard={tab === 'calendar'} class:visible={expanded} style={`--panel-width:${panelWidth}px;--panel-height:${panelHeight}px`} aria-busy={layoutBusy} aria-hidden={!expanded} inert={!expanded}>
      <header class="header">
        <nav class="tabs" aria-label="Фильтр задач">{#each tabs as item}<button class:active={tab === item.id} aria-label={item.label} aria-current={tab === item.id ? 'page' : undefined} title={item.label} on:click={() => selectTab(item.id)}><svelte:component this={item.icon} size={17} strokeWidth={1.8}/><span>{item.label}</span></button>{/each}</nav>
        <div class="header-actions">
          <button class="icon-button pin-button" class:selected={pinned} aria-label="Закрепить островок" aria-pressed={pinned} title={pinned ? 'Открепить' : 'Не сворачивать при уходе курсора'} on:click={() => pinned = !pinned}><Pin size={17}/></button>
          <button class="icon-button" class:selected={settingsOpen} aria-label="Настройки" aria-expanded={settingsOpen} title="Настройки" on:click={() => settingsOpen = !settingsOpen}><SlidersHorizontal size={18}/></button>
          <button class="icon-button collapse-button" aria-label="Свернуть" title="Свернуть · Esc" on:click={collapse}><ChevronDown size={18}/></button>
        </div>
      </header>
      {#if activeReminder}<ReminderNotice task={activeReminder} phase={reminderPhase} remaining={reminderQueue.length} leaving={reminderClosing} inline open={() => void dismissReminder(true)} dismiss={() => void dismissReminder()} hover={value => reminderHovered = value}/>{/if}
      {#if settingsOpen}
        <div class="settings-panel">
          <div class="settings-title">Островок<button class="icon-button" aria-label="Закрыть настройки" on:click={() => settingsOpen = false}><X size={15}/></button></div>
          <AppearancePicker value={appearance} change={style => updateAppearance(style)}/>
          <label><span>Жидкий край</span><input type="checkbox" checked={liquidEnabled} on:change={event => updateAppearance(appearance, event.currentTarget.checked)}/></label>
          <label><span>Эквалайзер музыки</span><input type="checkbox" checked={equalizerEnabled} on:change={event => updateAppearance(appearance, liquidEnabled, event.currentTarget.checked)}/></label>
          {#if appearanceError}<p class="appearance-error" role="status">{appearanceError}</p>{/if}
          <WidgetPreferences settings={widgetSettings} save={saveWidgetSettings} busy={settingsBusy} error={settingsError} {shortcutMode}/>
          <button class="exit-button" aria-label="Выход" on:click={exitApp}><Power size={15}/> Завершить приложение</button>
        </div>
      {/if}
      <div class="view-stage" bind:this={viewStage}>
      {#if tab === 'home'}
        <HomePanel active={expanded && visible} {tasks} {now} {media} {mediaError} {weather} {focusSeconds} {focusTotalSeconds} {timerRunning} {widgetSettings} {pinned} {reducedMotion} {mediaBusy} navigate={selectTab} createTask={openComposer} toggleFocus={toggleTimer} addMinute={addFocusMinute} resetFocus={() => setFocusMinutes(focusMinutes)} mediaCommand={compactCommand} playMusic={playFromHome} openSettings={() => settingsOpen = true}/>
      {:else if tab === 'clipboard'}
        <ClipboardPanel paste={pasteClipboard} {automaticPaste}/>
      {:else if tab === 'music'}
        <MusicPanel {media} {mediaError} bind:preferred={preferredMedia} refresh={refreshMedia}/>
      {:else if tab === 'weather'}
        <WeatherPanel {weather} {now} loading={weatherLoading} refresh={refreshWeather}/>
      {:else if tab === 'calendar'}
        <CalendarPanel {tasks} {now} {weather} {refresh} planner={calendarPlanner} changeLayout={changeCalendarLayout} bind:selected={selectedDate} bind:interacting={calendarBusy} openNotes={() => selectTab('notes')}/>
      {:else}
      <div class="workspace" class:notes-workspace={tab === 'notes'}>
        {#if tab === 'notes'}
          {#await import('./lib/NotesPanel.svelte')}<div class="notes-loading">Открываю заметки…</div>{:then {default:NotesPanel}}<NotesPanel bind:this={notesPanel} {refresh}/>{:catch err}<p class="error" role="alert">Не удалось открыть редактор: {String(err)}</p>{/await}
        {:else}
        <section class="tasks-panel content" aria-label="Задачи">
          <div class="panel-heading"><div><h1>{tabTitle}<span>{filteredTasks.length}</span></h1><p class="meta">{tab === 'tasks' ? `${datedTasks.length} со сроком · ${undatedTasks.length} без срока` : now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}</p></div><button class="icon-button add-small" aria-label="Новая задача" title="Новая задача" on:click={openComposer}><Plus size={19}/></button></div>
          {#if error || refreshError}<div class="error" role="alert"><span>{error || refreshError}</span><button aria-label="Убрать ошибку" on:click={() => { error = ''; refreshError = ''; }}><X size={13}/></button></div>{/if}
          {#if showForm}
            <form class="task-form" on:submit|preventDefault={saveTask}>
              <div class="field-heading"><span>Новая задача</span><button class="icon-button" type="button" title="Отмена" aria-label="Отмена" on:click={() => showForm = false}><X size={16}/></button></div>
              <input class="title-field" aria-label="Название задачи" bind:this={titleInput} type="text" maxlength="200" placeholder="Что нужно сделать?" bind:value={title}/>
              <FormattedInput label="Заметка к задаче" placeholder="Добавить заметку" bind:value={notes} disabled={busy}/>
              <label class="date-field"><CalendarDays size={15}/><input aria-label="Дедлайн" type="datetime-local" bind:value={dateTime}/></label>
              <select aria-label="Приоритет" bind:value={priority}><option value={0}>Обычный приоритет</option><option value={1}>Важная задача</option><option value={2}>Срочная задача</option></select>
              <div class="form-bottom"><span><Bell size={12}/>{dateTime ? 'За 30 минут до срока' : 'Без напоминания'}</span><button class="submit-task" type="submit" disabled={busy || !title.trim()}>{busy ? 'Сохраняю…' : 'Создать'}<Plus size={15}/></button></div>
            </form>
          {:else}
            {#if tab === 'tasks'}<div class="task-filters" role="group" aria-label="Фильтр списка задач">{#each [{id:'all',label:'Все'},{id:'dated',label:'Со сроком'},{id:'undated',label:'Без срока'}] as filter}<button class:active={taskFilter === filter.id} aria-pressed={taskFilter === filter.id} on:click={() => taskFilter = filter.id as typeof taskFilter}>{filter.label}</button>{/each}</div>{/if}
            <div class="task-list">
              {#each filteredTasks as task (task.id)}
                <article class="task-item" class:done={task.status === 'done'} class:reminder-highlight={highlightedTask === task.id} data-task-id={task.id}>
                  <button class="task-checkbox" class:checked={task.status === 'done'} aria-label="Изменить статус задачи" on:click={() => toggleDone(task)}><Check size={12} strokeWidth={3}/></button>
                  <div class="task-main"><div class="task-name">{task.title}</div>{#if task.notes}<div class="task-notes"><FormattedText value={task.notes}/></div>{/if}<div class="task-due" class:overdue={overdue(task)}>{#if task.due_at}{dateLabel(task.due_at)}{:else}Без дедлайна{/if}</div>
                    {#if editId === task.id}<div class="inline-editor"><input aria-label="Новый дедлайн" type="datetime-local" bind:value={editDate}/><button aria-label="Сохранить срок" on:click={() => saveEdit(task)}><Check size={14}/></button><button aria-label="Отменить" on:click={() => editId = null}><X size={14}/></button></div>{/if}
                    {#if deleteId === task.id}<div class="delete-confirm"><span>Удалить задачу?</span><button on:click={() => deleteId = null}>Отмена</button><button class="confirm-delete" on:click={() => removeTask(task)}>Удалить навсегда</button></div>{/if}
                  </div>
                  <div class="task-actions">{#if task.status === 'open'}<button class="priority-indicator" class:priority-med={task.priority === 1} class:priority-hot={task.priority === 2} aria-label="Сменить приоритет" title="Сменить приоритет" on:click={() => cyclePriority(task)}><Flag size={13} fill={task.priority ? 'currentColor' : 'none'}/></button>{/if}<button aria-label="Изменить дедлайн" title="Изменить дедлайн" on:click={() => startEditing(task)}><Pencil size={13}/></button><button aria-label="Удалить задачу" title="Удалить" on:click={() => { deleteId = task.id; editId = null; }}><Trash2 size={13}/></button></div>
                </article>
              {:else}
                <div class="empty"><span class="empty-symbol"><Check size={24} strokeWidth={1.4}/></span><b>{tab === 'done' ? 'Нет завершённых задач' : tab === 'today' ? 'Нет задач на сегодня' : 'Нет задач'}</b>{#if tab !== 'done'}<button on:click={openComposer}><Plus size={14}/> Добавить задачу</button>{/if}</div>
              {/each}
            </div>
            <button class="add-task" on:click={openComposer}><Plus size={17}/><span>Добавить задачу</span><span class="add-shortcut">+</span></button>
          {/if}
        </section>
        {/if}
        <aside class="focus-panel" class:reminders-only={tab !== 'today'}>
          {#if tab === 'today'}
          <div class="focus-top"><div class="timer-dial" class:timer-active={timerRunning}><svg viewBox="0 0 104 104" aria-hidden="true"><circle class="timer-track" cx="52" cy="52" r="46"/><circle class="timer-progress" cx="52" cy="52" r="46" pathLength="1" stroke-dasharray="1" stroke-dashoffset={1 - timerProgress}/></svg><span class="timer-value">{countdown(focusSeconds)}</span></div><div class="timer-actions"><button class="timer-toggle" aria-label={timerRunning ? 'Приостановить таймер' : 'Запустить таймер'} title={timerRunning ? 'Пауза' : 'Начать фокус'} on:click={toggleTimer}>{#if timerRunning}<Pause size={15} fill="currentColor"/>Пауза{:else}<Play size={15} fill="currentColor"/>Старт{/if}</button><div class="timer-secondary"><button aria-label="Добавить минуту" on:click={addFocusMinute}>+1 мин</button><button class="timer-reset" aria-label="Сбросить таймер" title="Сбросить" on:click={() => setFocusMinutes(focusMinutes)}>Сброс</button></div></div></div>
          <div class="focus-caption">{timerRunning ? `до ${new Date(now.getTime()+focusSeconds*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}` : 'Таймер'} · всего {Math.round(focusTotalSeconds/60)} мин</div>
          <div class="timer-presets">{#each [15, 25, 45] as minutes}<button class:active={focusMinutes === minutes} aria-pressed={focusMinutes === minutes} on:click={() => setFocusMinutes(minutes)}>{minutes} мин</button>{/each}</div>
          <TimerDuration minutes={focusMinutes} total={focusTotalSeconds} set={setFocusMinutes} add={addFocusMinutes}/>
          {/if}
          <div class="reminders-heading"><Bell size={14}/><span>Напоминания</span><span class="reminders-count">{openTasks.filter(task => task.due_at).length}</span></div>
          <div class="reminders">{#each reminders as task}<button class="reminder" title={task.title} on:click={() => { tab = new Date(task.due_at!) < dayEnd(now) ? 'today' : 'tasks'; showForm = false; }}><span class="reminder-dot" class:late={overdue(task)}></span><span><b>{task.title}</b><small>{dateLabel(task.due_at!)}</small></span></button>{:else}<div class="no-reminders">Нет напоминаний</div>{/each}</div>
          <QuickReminder {refresh}/>
        </aside>
      </div>
      {/if}
      </div>
      <footer><span><i></i>{tab === 'notes' ? 'Записи только на этом компьютере' : busy ? 'Сохраняю…' : 'Сохранено на этом компьютере'}</span><span>personal island</span></footer>
    </main>
  </div>
</div>
<SelectionToolbar/>
