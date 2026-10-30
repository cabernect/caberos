// Fetch the Microsoft Execution Containers (MXC) binaries the Windows installer
// bundles into frontend/src-tauri/resources/mxc.
//
// MXC is how the Windows desktop app sandboxes shell commands without asking the
// user to install Docker Desktop or WSL. The binaries only ship inside the
// @microsoft/mxc-sdk npm package (MIT), so this pins a version and verifies every
// file's SHA-256 before it can reach an installer. wxc-host-prep.exe in particular
// is run elevated by the desktop app, so a swapped file here must fail the build.
//
// Upgrading: change MXC_VERSION, then replace the hashes with the values printed by
// `Get-FileHash -Algorithm SHA256` on the new package's bin/x64 files.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MXC_VERSION = "0.9.0";

const FILES = [
  {
    member: "package/bin/x64/wxc-exec.exe",
    name: "wxc-exec.exe",
    sha256: "819ecd9b08a8dcb2376d489c0352087468bf56800ab059f57d38901d7743049e",
  },
  {
    member: "package/bin/x64/wxc-host-prep.exe",
    name: "wxc-host-prep.exe",
    sha256: "eae22ec72df6b350aebbaa8d18e6790d328d11939bdd7a61ef0a38a62d4dcbd6",
  },
  {
    member: "package/LICENSE.md",
    name: "LICENSE-mxc-sdk.md",
    sha256: "d9a1b1e30d633d5732ea18e3cba9538d293ebc53e1a9e4e96ab739e0c5c4f1cb",
  },
];

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const outDir = join(rootDir, "frontend", "src-tauri", "resources", "mxc");

const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");

function fail(message) {
  console.error(`[fetch-mxc] ${message}`);
  process.exit(1);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.error || result.status !== 0) {
    fail(`'${command} ${args.join(" ")}' failed${result.error ? `: ${result.error.message}` : ""}`);
  }
}

if (process.platform !== "win32") {
  console.log("[fetch-mxc] MXC is Windows-only; nothing to fetch.");
  process.exit(0);
}

if (FILES.every((f) => existsSync(join(outDir, f.name)) && sha256(join(outDir, f.name)) === f.sha256)) {
  console.log(`[fetch-mxc] @microsoft/mxc-sdk ${MXC_VERSION} already present and verified.`);
  process.exit(0);
}

const work = mkdtempSync(join(tmpdir(), "caberos-mxc-"));
try {
  const tarball = `mxc-sdk-${MXC_VERSION}.tgz`;
  const url = `https://registry.npmjs.org/@microsoft/mxc-sdk/-/${tarball}`;
  console.log(`[fetch-mxc] downloading ${url}`);
  const response = await fetch(url);
  if (!response.ok) {
    fail(`download failed: HTTP ${response.status} ${response.statusText} for ${url}`);
  }
  writeFileSync(join(work, tarball), Buffer.from(await response.arrayBuffer()));

  // Relative paths only: Git for Windows puts a GNU tar first on PATH, and it reads
  // 'C:\...' as host:file. Running inside the work dir sidesteps drive letters.
  run("tar", ["-xzf", tarball, ...FILES.map((f) => f.member)], { cwd: work });

  mkdirSync(outDir, { recursive: true });
  for (const file of FILES) {
    const extracted = join(work, ...file.member.split("/"));
    const actual = sha256(extracted);
    if (actual !== file.sha256) {
      fail(
        `${file.name} hash mismatch for @microsoft/mxc-sdk@${MXC_VERSION}\n` +
          `  expected ${file.sha256}\n  actual   ${actual}\n` +
          "Refusing to bundle it. If you are upgrading on purpose, update MXC_VERSION and the pinned hashes.",
      );
    }
    copyFileSync(extracted, join(outDir, file.name));
  }
  console.log(`[fetch-mxc] bundled ${FILES.length} verified files into ${outDir}`);
} finally {
  rmSync(work, { recursive: true, force: true });
}
