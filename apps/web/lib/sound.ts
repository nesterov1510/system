// Короткий приятный звук уведомления (Web Audio, без файла).
// Браузер блокирует автозапуск аудио до первого клика по странице —
// primeAudio() вызывается по первому нажатию, чтобы дальше звук работал.

let _ctx: AudioContext | null = null;

function ctx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const AC: typeof AudioContext | undefined =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!_ctx) _ctx = new AC();
  if (_ctx.state === "suspended") _ctx.resume().catch(() => {});
  return _ctx;
}

/** Вызывайте при первом взаимодействии пользователя (клик), чтобы разблокировать аудио. */
export function primeAudio() {
  ctx();
}

/** Проиграть короткое двухнотное уведомление. */
export function playNotify() {
  const c = ctx();
  if (!c) return;
  const t0 = c.currentTime;
  const tones: Array<[number, number]> = [
    [880, 0.0],
    [660, 0.16],
  ];
  for (const [freq, start] of tones) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    const s = t0 + start;
    gain.gain.setValueAtTime(0.0001, s);
    gain.gain.exponentialRampToValueAtTime(0.18, s + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, s + 0.18);
    osc.connect(gain).connect(c.destination);
    osc.start(s);
    osc.stop(s + 0.2);
  }
}
