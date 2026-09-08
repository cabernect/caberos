const STORAGE_KEY = "caberos-sidebar-collapsed";

export function getStoredSidebarCollapsed(storage: Storage | null = typeof window !== "undefined" ? window.localStorage : null): boolean | null {
  const value = storage?.getItem(STORAGE_KEY);
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

export function setStoredSidebarCollapsed(collapsed: boolean, storage: Storage | null = typeof window !== "undefined" ? window.localStorage : null) {
  try {
    storage?.setItem(STORAGE_KEY, String(collapsed));
  } catch {}
}
