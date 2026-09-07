export type WebTheme = "glacier" | "classic-dark";

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;
type ThemeRoot = { readonly dataset: DOMStringMap };

export const THEME_STORAGE_KEY = "bomana:web:theme:v1";

export function readTheme(storage: ThemeStorage = localStorage): WebTheme {
  try {
    return storage.getItem(THEME_STORAGE_KEY) === "classic-dark" ? "classic-dark" : "glacier";
  } catch {
    return "glacier";
  }
}

export function saveTheme(theme: WebTheme, storage: ThemeStorage = localStorage): void {
  try { storage.setItem(THEME_STORAGE_KEY, theme); } catch { /* browser storage may be unavailable */ }
}

export function applyTheme(theme: WebTheme, root: ThemeRoot = document.documentElement): void {
  root.dataset.theme = theme;
}

export function applySavedTheme(
  root: ThemeRoot = document.documentElement,
  storage: ThemeStorage = localStorage,
): WebTheme {
  const theme = readTheme(storage);
  applyTheme(theme, root);
  return theme;
}
