const SYMBOL_PATTERNS = [
  /\b(?:function|async function)\s+([A-Za-z0-9_]+)/g,
  /\bclass\s+([A-Za-z0-9_]+)/g,
  /\b(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(/g,
  /\bexport\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)/g,
  /\bexport\s+class\s+([A-Za-z0-9_]+)/g,
  /\bexport\s+const\s+([A-Za-z0-9_]+)/g,
];

const TOKEN_SPLIT = /[^A-Za-z0-9]+/;

function extractSymbols(line) {
  const symbols = new Set();

  for (const pattern of SYMBOL_PATTERNS) {
    pattern.lastIndex = 0;
    for (const match of line.matchAll(pattern)) {
      if (match[1]) {
        symbols.add(match[1]);
      }
    }
  }

  return symbols;
}

function toTokens(value) {
  return value
    .split(TOKEN_SPLIT)
    .filter(Boolean)
    .map((token) => token.toLowerCase())
    .filter((token) => token.length > 2);
}

export function parseUnifiedDiff(diffText) {
  const files = [];
  const allSymbols = new Set();
  let currentFile = null;

  for (const line of diffText.split("\n")) {
    if (line.startsWith("diff --git ")) {
      if (currentFile) {
        files.push(finalizeFile(currentFile));
      }
      currentFile = {
        path: "",
        addedLines: [],
        removedLines: [],
      };
      continue;
    }

    if (!currentFile) {
      continue;
    }

    if (line.startsWith("+++ b/")) {
      currentFile.path = line.slice("+++ b/".length);
      continue;
    }

    if (line.startsWith("+") && !line.startsWith("+++")) {
      currentFile.addedLines.push(line.slice(1));
      for (const symbol of extractSymbols(line)) {
        allSymbols.add(symbol);
      }
      continue;
    }

    if (line.startsWith("-") && !line.startsWith("---")) {
      currentFile.removedLines.push(line.slice(1));
      for (const symbol of extractSymbols(line)) {
        allSymbols.add(symbol);
      }
    }
  }

  if (currentFile) {
    files.push(finalizeFile(currentFile));
  }

  return {
    files,
    symbols: allSymbols,
  };
}

function finalizeFile(file) {
  const basename = file.path.split("/").pop() ?? file.path;
  const pathTokens = new Set(toTokens(file.path));
  const contentTokens = new Set([
    ...file.addedLines.flatMap(toTokens),
    ...file.removedLines.flatMap(toTokens),
  ]);

  return {
    path: file.path,
    basename,
    addedLines: file.addedLines,
    removedLines: file.removedLines,
    pathTokens,
    contentTokens,
  };
}
