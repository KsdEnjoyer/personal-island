/** Whole-island entrance/exit. Native hide happens only after this resolves. */
export function createPresence(element: HTMLElement, reduced: () => boolean) {
  let animation: Animation | undefined;
  let deadline = 0;
  function run(show: boolean) {
    const current = animation ? getComputedStyle(element) : null;
    const from = current ? { opacity: current.opacity, transform: current.transform }
      : show ? { opacity: '0', transform: 'translateY(-14px) scale(.985)' }
      : { opacity: '1', transform: 'translateY(0) scale(1)' };
    animation?.cancel();
    const duration = reduced() ? 0 : show ? 380 : 260;
    const next = element.animate([from, show
      ? { opacity: '1', transform: 'translateY(0) scale(1)' }
      : { opacity: '0', transform: 'translateY(-12px) scale(.985)' }],
      { duration, easing: show ? 'cubic-bezier(.22,1,.36,1)' : 'cubic-bezier(.4,0,.8,.4)', fill: 'both' });
    animation = next;
    deadline = performance.now() + duration + 150;
    return next.finished.catch(() => {}).then(() => {
      if (animation === next && show) { next.cancel(); animation = undefined; }
    });
  }
  return {
    show: () => run(true), hide: () => run(false),
    flush() { if (animation && performance.now() >= deadline && animation.playState !== 'finished') animation.finish(); },
    reset() { animation?.cancel(); animation = undefined; },
  };
}
