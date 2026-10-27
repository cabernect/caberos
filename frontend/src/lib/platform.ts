/**
 * Platform detection — CaberOS runs on macOS, Linux and Windows.
 * Used for shortcut-hint glyphs and platform-typical path examples.
 */
const nav = navigator as Navigator & {
  userAgentData?: { platform?: string };
};
const platform = nav.userAgentData?.platform ?? navigator.platform ?? "";

export const IS_MAC = /mac/i.test(platform);
export const IS_WINDOWS = /win/i.test(platform);

/** Shortcut hint label: "⌘K" on macOS, "Ctrl+K" elsewhere. */
export function modShortcut(key: string): string {
  return IS_MAC ? `⌘${key}` : `Ctrl+${key}`;
}

/** A plausible Chrome/Chromium path for the platform, used as a placeholder. */
export const CHROME_PATH_EXAMPLE = IS_MAC
  ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  : IS_WINDOWS
    ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    : "/usr/bin/chromium";
