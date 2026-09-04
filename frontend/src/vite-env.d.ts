/// <reference types="vite/client" />

/**
 * Version of the desktop shell this dashboard was bundled with, injected by
 * Vite from package.json. Compared against the gateway's reported version to
 * detect an update that replaced the shell but left the bundled gateway stale.
 */
declare const __APP_VERSION__: string;
