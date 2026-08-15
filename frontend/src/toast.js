// Tiny global pub/sub, no context/provider needed -- api.js (outside any
// component tree) calls showToast() directly whenever a request fails, and
// ToastHost (mounted once in App.jsx) is the only subscriber. This is what
// makes every API error visible platform-wide regardless of scroll
// position, without touching each component's own inline error handling.
let listeners = [];
let nextId = 1;

export function showToast(message, tone = "danger") {
  const toast = { id: nextId++, message, tone };
  listeners.forEach((fn) => fn(toast));
}

export function subscribeToast(fn) {
  listeners.push(fn);
  return () => { listeners = listeners.filter((l) => l !== fn); };
}
