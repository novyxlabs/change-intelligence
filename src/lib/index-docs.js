import { readdir, readFile } from "node:fs/promises";
import { join, extname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const DOC_EXTENSIONS = new Set([".md", ".mdx", ".txt"]);
const TOKEN_SPLIT = /[^A-Za-z0-9]+/;

function tokenize(value) {
  return value
    .split(TOKEN_SPLIT)
    .filter(Boolean)
    .map((token) => token.toLowerCase())
    .filter((token) => token.length > 2);
}

function extractHeadings(content) {
  const headings = [];
  for (const line of content.split("\n")) {
    if (line.startsWith("#")) {
      headings.push(line.replace(/^#+\s*/, "").trim());
    }
  }
  return headings;
}

async function walk(root, current = root) {
  const entries = await readdir(current, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const path = join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(root, path)));
      continue;
    }

    if (DOC_EXTENSIONS.has(extname(entry.name))) {
      files.push(path);
    }
  }

  return files;
}

export async function indexDocs(root) {
  const normalizedRoot = root instanceof URL ? fileURLToPath(root) : root;
  const files = await walk(normalizedRoot);
  const docs = [];

  for (const file of files) {
    const content = await readFile(file, "utf8");
    const headings = extractHeadings(content);
    docs.push({
      path: file,
      relativePath: relative(normalizedRoot, file),
      headings,
      tokens: new Set([
        ...tokenize(relative(normalizedRoot, file)),
        ...headings.flatMap(tokenize),
        ...tokenize(content),
      ]),
      content,
    });
  }

  return docs;
}
