// Tiny localStorage helpers for view-state that must survive tab switches and
// reloads. Same pattern the Ingest views use. Writes happen inside mutationFns
// (not React effects) so a result lands even if the component unmounted while
// the request was in flight; reads run in a useState initializer on (re)mount.

export function readLS<T extends object = Record<string, unknown>>(key: string): T {
  try {
    return JSON.parse(localStorage.getItem(key) || "{}") as T;
  } catch {
    return {} as T;
  }
}

export function patchLS(key: string, patch: Record<string, unknown>): void {
  try {
    const cur = readLS(key);
    localStorage.setItem(key, JSON.stringify({ ...cur, ...patch }));
  } catch {
    /* quota / disabled storage — best-effort */
  }
}
