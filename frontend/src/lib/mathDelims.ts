/** Models frequently emit LaTeX with \(...\) and \[...\] delimiters.
 * Markdown's escape rules turn `\(` into a literal `(` before any remark
 * plugin runs, so conversion must happen on the raw source: rewrite the
 * delimiters to remark-math's $ / $$ syntax while skipping fenced code
 * blocks and inline code spans, where they must stay literal.
 * Indented code is not tracked — a rare form models don't emit. */
export function normalizeMathDelims(src: string): string {
  const out: string[] = [];
  let i = 0;
  let fence: { char: string; len: number } | null = null;
  let lineStart = true;

  while (i < src.length) {
    if (lineStart) {
      const m = /^ {0,3}(`{3,}|~{3,})/.exec(src.slice(i));
      if (m) {
        const marker = m[1];
        if (fence === null) fence = { char: marker[0], len: marker.length };
        else if (marker[0] === fence.char && marker.length >= fence.len) fence = null;
        const nl = src.indexOf("\n", i);
        if (nl === -1) {
          out.push(src.slice(i));
          break;
        }
        out.push(src.slice(i, nl + 1));
        i = nl + 1;
        continue;
      }
      lineStart = false;
    }

    const ch = src[i];
    if (ch === "\n") {
      out.push(ch);
      i++;
      lineStart = true;
      continue;
    }
    if (fence !== null) {
      const nl = src.indexOf("\n", i);
      if (nl === -1) {
        out.push(src.slice(i));
        break;
      }
      out.push(src.slice(i, nl + 1));
      i = nl + 1;
      lineStart = true;
      continue;
    }
    if (ch === "`") {
      const run = /^`+/.exec(src.slice(i))![0];
      const close = src.indexOf(run, i + run.length);
      const end = close === -1 ? i + run.length : close + run.length;
      out.push(src.slice(i, end));
      i = end;
      continue;
    }
    if (src.startsWith("\\(", i)) {
      const close = src.indexOf("\\)", i + 2);
      if (close !== -1) {
        out.push("$" + src.slice(i + 2, close) + "$");
        i = close + 2;
        continue;
      }
    }
    if (src.startsWith("\\[", i)) {
      const close = src.indexOf("\\]", i + 2);
      if (close !== -1) {
        out.push("$$" + src.slice(i + 2, close) + "$$");
        i = close + 2;
        continue;
      }
    }
    out.push(ch);
    i++;
    if (ch !== " " && ch !== "\t") lineStart = false;
  }
  return out.join("");
}
