type Spring = { value: number; velocity: number; target: number };
export type AudioFrame = { bands: number[]; bass: number; level: number; impact: number; available: boolean };
type Options = {
  onSize: (width: number, height: number) => void;
  reducedMotion: boolean;
  liquid: boolean;
};

export const ISLAND = {
  collapsed: { width: 272, height: 56 },
  expanded: { width: 704, height: 458 },
};

/** A single persistent silhouette: the native window only shrinks after it settles. */
export function createLiquidIsland(canvas: HTMLCanvasElement, options: Options) {
  const ctx = canvas.getContext('2d')!;
  const width: Spring = { value: 272, velocity: 0, target: 272 };
  const height: Spring = { value: 56, velocity: 0, target: 56 };
  const pull: Spring = { value: 0, velocity: 0, target: 0 };
  const pointer: Spring = { value: 0.5, velocity: 0, target: 0.5 };
  const music: Spring = { value: 0, velocity: 0, target: 0 };
  let viewportWidth = 336;
  let viewportHeight = 144;
  let ratio = 1;
  let frame = 0;
  let lastTime = 0;
  let time = 0;
  let pulse = 0;
  let expanded = false;
  let compact = { width: 272, height: 56 };
  let expandedSize = { ...ISLAND.expanded };
  let disposed = false;
  let settle: (() => void) | undefined;
  let transitionStarted = 0;
  let reducedMotion = options.reducedMotion;
  let liquid = options.liquid;
  let equalizer = true;
  let layoutWidth = -1;
  let layoutHeight = -1;
  let fill = '#000';
  let edge = '#292929';
  let shown = true;
  const bands = Array(10).fill(0) as number[];
  let audio: AudioFrame = {bands:Array(10).fill(0),bass:0,level:0,impact:0,available:false};
  let audioAt = -Infinity;
  let bass = 0;
  let impact = 0;

  const resize = () => {
    const box = canvas.getBoundingClientRect();
    viewportWidth = box.width;
    viewportHeight = box.height;
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(viewportWidth * ratio);
    canvas.height = Math.round(viewportHeight * ratio);
    draw();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);

  function integrate(spring: Spring, dt: number, stiffness = 400, damping = 40) {
    const steps = Math.max(1, Math.ceil(dt / (1 / 120)));
    const step = dt / steps;
    for (let i = 0; i < steps; i++) {
      spring.velocity += ((spring.target - spring.value) * stiffness - spring.velocity * damping) * step;
      spring.value += spring.velocity * step;
    }
  }

  function draw() {
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, viewportWidth, viewportHeight);
    const w = width.value;
    const h = height.value;
    const x = (viewportWidth - w) / 2;
    const progress = Math.max(0, Math.min(1, (w - 272) / (704 - 272)));
    const radius = 20 + 8 * progress;
    const shoulder = 24;
    const wave: [number, number][] = [];
    const count = 144;
    for (let i = 0; i <= count; i++) {
      const u = i / count;
      const edge = Math.sin(u * Math.PI);
      const distance = (u - pointer.value) / (expanded ? 0.13 : 0.23);
      const attraction = pull.value * Math.exp(-distance * distance * 2);
      const idle = Math.sin(u * Math.PI * (expanded ? 15 : 3) + time * 1.2) * (expanded ? 2.5 : 2.4);
      const ripple = Math.sin(u * Math.PI * 16 - time * 10) * pulse * 5;
      // Only the stroked waveform responds to audio. The filled body below is
      // drawn separately and never uses frequency levels or transient impact.
      const bandPosition = Math.abs(u - .5) * 2 * (bands.length - 1);
      const bin = Math.min(bands.length - 2, Math.floor(bandPosition));
      const band = bands[bin] + (bands[bin + 1] - bands[bin]) * (bandPosition - bin);
      // Give ordinary passages enough range, then punch harder on transients.
      // Phase follows measured energy, never a free-running music animation.
      const energy = Math.pow(band, .7);
      const carrier = (Math.sin(u * Math.PI * 20 + band * 1.4)
        + Math.sin(u * Math.PI * 36 - bass * .7) * .24) / 1.24;
      // Compress the envelope, not individual samples: clipping samples made
      // every inward crest hit the same flat ceiling. Shift the centre down
      // with energy so both halves stay curved without entering the controls.
      const amplitude = 38 * Math.tanh((energy * (20 + impact * 24) + bass * 7) / 34);
      const inward = 4 * (1 - Math.exp(-amplitude / 8));
      const spectrum = ((amplitude - inward) / 2 + carrier * (amplitude + inward) / 2) * music.value;
      const ambient = liquid ? idle * (1 - music.value * .96) + attraction + ripple : 0;
      wave.push([x + radius + u * (w - radius * 2), h - 2 + (!reducedMotion ? (ambient + spectrum) * edge : 0)]);
    }
    ctx.beginPath();
    ctx.moveTo(x - shoulder, 0);
    ctx.bezierCurveTo(x - 7, 0, x, 8, x, 25);
    ctx.lineTo(x, h - radius);
    ctx.quadraticCurveTo(x, h, x + radius, h);
    ctx.lineTo(x + w - radius, h);
    ctx.quadraticCurveTo(x + w, h, x + w, h - radius);
    ctx.lineTo(x + w, 25);
    ctx.bezierCurveTo(x + w, 8, x + w + 7, 0, x + w + shoulder, 0);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.shadowColor = 'rgba(0,0,0,.38)';
    ctx.shadowBlur = 14;
    ctx.shadowOffsetY = 9;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;
    ctx.beginPath();
    ctx.moveTo(wave[0][0], wave[0][1]);
    traceEdge(wave);
    ctx.lineWidth = (expanded ? 1.4 : 2) + impact * music.value * .6;
    ctx.strokeStyle = pulse > .05 ? `rgba(255,177,42,${.2 + pulse * .35})` : music.value > .05 && !reducedMotion && equalizer ? `rgba(160,213,180,${.25 + music.value * .3 + impact * .18})` : edge;
    ctx.lineCap = 'round';
    // A restrained halo follows the hit; it never changes the body shadow.
    ctx.shadowColor = 'rgba(160,213,180,.35)';
    ctx.shadowBlur = equalizer && !reducedMotion ? impact * music.value * 4 : 0;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // Only expand/collapse springs change the body and its DOM hitbox.
    const nextWidth = Math.round(w * 10) / 10;
    const nextHeight = Math.round(h * 10) / 10;
    if (nextWidth !== layoutWidth || nextHeight !== layoutHeight) {
      layoutWidth = nextWidth; layoutHeight = nextHeight;
      options.onSize(nextWidth, nextHeight);
    }
  }

  function traceEdge(points:[number,number][], offset=0) {
    for (let i=1;i<points.length-1;i++) {
      const [x,y] = points[i]; const next = points[i+1];
      ctx.quadraticCurveTo(x,y+offset,(x+next[0])/2,(y+next[1])/2+offset);
    }
    const last = points[points.length-1];
    ctx.lineTo(last[0],last[1]+offset);
  }

  function tick(timestamp: number) {
    if (disposed) return;
    const elapsed = lastTime ? (timestamp - lastTime) / 1000 : 1 / 60;
    const dt = Math.min(elapsed, 1 / 30);
    lastTime = timestamp;
    time += dt;
    const fresh = audio.available && performance.now() - audioAt < 180 && music.target > 0;
    const follow = (value: number, target: number, release: number) => value + (target - value) * (1 - Math.exp(-dt / (target > value ? .004 : release)));
    for (let i = 0; i < bands.length; i++) bands[i] = follow(bands[i], fresh ? audio.bands[i] : 0, .055);
    bass = follow(bass, fresh ? audio.bass : 0, .08);
    impact = follow(impact, fresh ? audio.impact : 0, .045);
    if (reducedMotion || (document.hidden && elapsed > .5)) {
      width.value = width.target; height.value = height.target;
      width.velocity = 0; height.velocity = 0;
      pull.value = 0;
      music.value = music.target; music.velocity = 0;
    } else {
      integrate(width, dt);
      integrate(height, dt);
      integrate(pull, dt, 150, 25);
      integrate(pointer, dt, 140, 20);
      integrate(music, dt, 80, 18);
    }
    pulse *= Math.exp(-dt * 3);
    draw();
    if (settle && Math.abs(width.value - width.target) < .3 && Math.abs(height.value - height.target) < .3 && Math.abs(height.velocity) < 2) {
      width.value = width.target; height.value = height.target;
      settle(); settle = undefined;
    }
    // Keep the idle edge alive, pause completely when WebView is hidden.
    const moving = Math.abs(width.value - width.target) > .1 || Math.abs(height.value - height.target) > .1;
    if (!document.hidden && ((shown && !reducedMotion && (liquid || music.target > 0 || music.value > .01)) || moving || settle)) frame = requestAnimationFrame(tick);
    else frame = 0;
  }

  function wake() {
    if (!frame && !disposed) { lastTime = 0; frame = requestAnimationFrame(tick); }
  }
  const onVisibility = () => { if (!document.hidden) wake(); };
  document.addEventListener('visibilitychange', onVisibility);
  wake();

  return {
    setAudio(input: AudioFrame) {
      const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
      audio = {available:!!input?.available,bands:Array.from({length:10},(_,i)=>unit(input?.bands?.[i])),
        bass:unit(input?.bass),level:unit(input?.level),impact:unit(input?.impact)};
      audioAt = performance.now();
      if (shown && (liquid || music.target > 0) && !reducedMotion) wake();
    },
    setPalette(background: string, stroke: string) {
      if (fill === background && edge === stroke) return;
      fill = background; edge = stroke; wake();
    },
    setExpandedSize(w: number, h: number) { expandedSize = {width:w,height:h}; },
    setCompact(w: number, h: number) {
      if (compact.width === w && compact.height === h) return;
      compact = { width: w, height: h };
      if (!expanded) { width.target = w; height.target = h; wake(); }
    },
    setExpanded(value: boolean) {
      settle?.();
      expanded = value;
      const size = value ? expandedSize : compact;
      width.target = size.width;
      height.target = size.height;
      pull.target = 0;
      transitionStarted = performance.now();
      wake();
      return new Promise<void>(resolve => { settle = resolve; });
    },
    pointer(clientX: number, clientY: number) {
      if (reducedMotion || !liquid) return;
      const box = canvas.getBoundingClientRect();
      const x = (viewportWidth - width.value) / 2;
      pointer.target = Math.max(.05, Math.min(.95, (clientX - box.left - x) / width.value));
      const distanceY = clientY - box.top - height.value;
      pull.target = expanded
        ? Math.max(0, 1 - Math.abs(distanceY) / 65) * 9
        : Math.max(0, Math.min(10, (distanceY + 10) * .25)) * Math.max(0, 1 - Math.max(0, distanceY - 40) / 45);
      wake();
    },
    leave() { pull.target = 0; },
    flushOverdueTransition() {
      // A background WebView may suspend RAF. Native pointer heartbeats still
      // arrive, so a missed frame must not leave the closing window stuck open.
      if (!settle || performance.now() - transitionStarted < 1000) return;
      width.value = width.target; height.value = height.target;
      width.velocity = 0; height.velocity = 0;
      draw();
      settle(); settle = undefined;
    },
    celebrate() { pulse = 1; pull.velocity += 45; },
    configure(reduced: boolean, enabled: boolean, playing = false, visible = true, reactive = true) {
      reducedMotion = reduced; liquid = enabled; equalizer = reactive; shown = visible;
      music.target = playing && equalizer ? 1 : 0; wake();
    },
    destroy() {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      settle?.();
    },
  };
}
