// Dispatch to the platform-appropriate gateway build script.
//
// The gateway is packaged with PyInstaller, whose --add-data separator differs
// by platform, so the build steps genuinely differ and cannot be one script.
// This shim keeps a single entry point (`npm run build:gateway`, and Tauri's
// beforeBuildCommand) working on every platform.

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = dirname(fileURLToPath(import.meta.url));

const isWindows = process.platform === "win32";
const [command, args] = isWindows
  ? [
      "powershell",
      [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        join(scriptsDir, "build-gateway.ps1"),
      ],
    ]
  : ["bash", [join(scriptsDir, "build-gateway.sh")]];

const result = spawnSync(command, args, { stdio: "inherit" });

if (result.error) {
  console.error(`[build-gateway] could not run ${command}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
