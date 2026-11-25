// Share wheel sensitivity between the speaker icon and album artwork.
export function createVolumeWheelSteps() {
  let remainder = 0;
  let lastAt = 0;
  return {
    reset() { remainder = 0; lastAt = 0; },
    take(event: WheelEvent) {
      const now = Date.now();
      if (now - lastAt > 250) remainder = 0;
      lastAt = now;
      const pixels = event.deltaY * (event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 100 : 1);
      remainder -= pixels / 20;
      const change = Math.trunc(Math.round(remainder * 1e6) / 1e6);
      remainder -= change;
      return change;
    },
  };
}
