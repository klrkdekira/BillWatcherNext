/**
 * Node 25 and later define their own `localStorage` global, which is `undefined` unless the
 * process was started with `--localstorage-file`. Vitest's jsdom environment does not overwrite a
 * global Node already owns, so under those Nodes the tests saw Node's empty one instead of the
 * browser's. Point the global at jsdom's own storage, which is what a page would get.
 */
const dom = (globalThis as { jsdom?: { window: Window } }).jsdom;

if (dom) {
  for (const name of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      get: () => dom.window[name],
    });
  }
}
