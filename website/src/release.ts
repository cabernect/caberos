import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

type FrontendManifest = {
  version?: unknown;
};

const manifestPath = [
  resolve(process.cwd(), "../frontend/package.json"),
  resolve(process.cwd(), "frontend/package.json"),
].find((path) => existsSync(path));

if (!manifestPath) {
  throw new Error("Could not locate frontend/package.json");
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as FrontendManifest;

if (typeof manifest.version !== "string" || manifest.version.length === 0) {
  throw new Error("frontend/package.json must define the CaberOS product version");
}

export const releaseVersion = manifest.version;
export const releaseTag = `v${releaseVersion}`;
export const releaseUrl = `https://github.com/cabernect/caberos/releases/tag/${releaseTag}`;
export const downloadUrl = `https://github.com/cabernect/caberos/releases/download/${releaseTag}/CaberOS_${releaseVersion}_arm64.dmg`;
