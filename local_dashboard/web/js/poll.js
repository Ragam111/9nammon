import { assertPollInterval } from "./log-buffer.js";

/**
 * เรียก run ทันที แล้วเว้นช่วง intervalMs.
 * หยุดตั้งเวลาต่อเมื่อแท็บถูกซ่อน และเริ่มใหม่เมื่อแท็บกลับมา
 */
export function startVisibilityPoll(opts) {
  const intervalMs = assertPollInterval(opts.intervalMs);
  const setTimer = opts.setTimer || setTimeout;
  const clearTimer = opts.clearTimer || clearTimeout;
  const isHidden = opts.isHidden || function () { return false; };
  const listen = opts.listen || function (fn) {
    document.addEventListener("visibilitychange", fn);
    return function () { document.removeEventListener("visibilitychange", fn); };
  };
  let timer = null;
  let stopped = false;
  let inflight = false;

  async function tick() {
    if (timer != null) {
      clearTimer(timer);
      timer = null;
    }
    if (stopped || isHidden()) return;
    if (inflight) return;
    inflight = true;
    try {
      await opts.run();
    } finally {
      inflight = false;
    }
    if (!stopped && !isHidden()) timer = setTimer(tick, intervalMs);
  }

  const unlisten = listen(function () { tick(); });
  tick();
  return function stop() {
    stopped = true;
    if (timer != null) clearTimer(timer);
    timer = null;
    unlisten();
  };
}
