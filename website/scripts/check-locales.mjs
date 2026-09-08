import { existsSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("../src/content/docs/docs/", import.meta.url);
const rootPath = root.pathname;
const localeRoot = new URL("../src/content/docs/vi/docs/", import.meta.url).pathname;

function filesIn(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesIn(path) : entry.name.endsWith(".mdx") ? [path] : [];
  });
}

const missing = filesIn(rootPath)
  .map((path) => relative(rootPath, path))
  .filter((path) => !existsSync(join(localeRoot, path)));

if (missing.length > 0) {
  console.error(`Missing Vietnamese documentation pages:\n${missing.join("\n")}`);
  process.exit(1);
}

console.log(`Vietnamese documentation coverage complete: ${filesIn(rootPath).length} pages.`);
