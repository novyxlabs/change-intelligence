import { loadDiff } from "./lib/load-diff.js";
import { parseUnifiedDiff } from "./lib/parse-diff.js";
import { indexDocs } from "./lib/index-docs.js";
import { rankDocuments } from "./lib/rank-docs.js";
import { renderMarkdown } from "./lib/render-markdown.js";
import { normalizeAnalysisOptions } from "./lib/github.js";

export async function runAnalysis(options) {
  const normalizedOptions = normalizeAnalysisOptions(options);
  const diffText = await loadDiff(normalizedOptions);
  const diff = parseUnifiedDiff(diffText);
  const docs = await indexDocs(normalizedOptions.docs ?? normalizedOptions.docsDir ?? "docs");
  const recommendations = rankDocuments(diff, docs);

  const result = {
    summary: {
      changedFiles: diff.files.map((file) => file.path),
      changedSymbols: [...diff.symbols],
      docsAnalyzed: docs.length,
      recommendationCount: recommendations.length,
    },
    recommendations,
  };

  return {
    ...result,
    markdown: renderMarkdown(result),
  };
}
