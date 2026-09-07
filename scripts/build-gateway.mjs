// Dispatch to the platform-appropriate gateway build script.
//
// The gateway is packaged with PyInstaller, whose --add-data separator differs
// by platform, so the build steps genuinely differ and cannot be one script.
// This shim keeps a single entry point (`npm run build:gateway`, and Tauri's
// beforeBuildCommand) working on every platform.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = dirname(fileURLToPath(import.meta.url));
const rootDir = dirname(scriptsDir);

const isWindows = process.platform === "win32";

// Tauri's beforeBuildCommand runs this script, so a release that has already
// built and smoke-tested a gateway would otherwise ship a different, untested
// binary. Setting CABEROS_SKIP_GATEWAY_BUILD keeps the verified one.
if (process.env.CABEROS_SKIP_GATEWAY_BUILD) {
  const gateway = join(
    rootDir,
    "frontend",
    "src-tauri",
    "resources",
    "gateway",
    "caberos-gateway",
    isWindows ? "caberos-gateway.exe" : "caberos-gateway",
  );
  if (!existsSync(gateway)) {
    console.error(
      `[build-gateway] CABEROS_SKIP_GATEWAY_BUILD is set but no gateway exists at ${gateway}`,
    );
    process.exit(1);
  }
  console.log(`[build-gateway] reusing existing gateway at ${gateway}`);
  process.exit(0);
}
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
