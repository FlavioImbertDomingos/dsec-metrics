export type ThemePreference = "system" | "light" | "dark";

const KEY = "dsec-theme";

export function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Apply a preference to the document and remember it. */
export function applyPreference(pref: ThemePreference): void {
  try {
    if (pref === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for this page only.
  }
  const dark = pref === "dark" || (pref === "system" && systemPrefersDark());
  const root = document.documentElement;
  // Switch in one step: without this, elements with color transitions pass through
  // low-contrast in-between colors for a moment.
  root.classList.add("theme-switching");
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  getComputedStyle(root).getPropertyValue("color"); // apply new colors before transitions return
  root.classList.remove("theme-switching");
}
