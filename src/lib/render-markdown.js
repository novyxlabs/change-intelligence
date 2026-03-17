export function renderMarkdown(result) {
  const lines = [
    "# Change Intelligence Report",
    "",
    "## Summary",
    "",
    `- Changed files: ${result.summary.changedFiles.length}`,
    `- Changed symbols: ${result.summary.changedSymbols.length}`,
    `- Docs analyzed: ${result.summary.docsAnalyzed}`,
    `- Recommended docs updates: ${result.summary.recommendationCount}`,
    "",
  ];

  if (result.summary.changedFiles.length > 0) {
    lines.push("## Changed Files", "");
    for (const file of result.summary.changedFiles) {
      lines.push(`- \`${file}\``);
    }
    lines.push("");
  }

  if (result.summary.changedSymbols.length > 0) {
    lines.push("## Changed Symbols", "");
    for (const symbol of result.summary.changedSymbols) {
      lines.push(`- \`${symbol}\``);
    }
    lines.push("");
  }

  lines.push("## Recommended Docs", "");

  for (const recommendation of result.recommendations) {
    lines.push(`### ${recommendation.relativePath}`);
    lines.push("");
    lines.push(`Score: **${recommendation.score}**`);
    lines.push("");
    lines.push("Evidence:");
    for (const item of recommendation.evidence) {
      lines.push(`- ${item}`);
    }
    lines.push("");
    lines.push("Update focus:");
    for (const item of recommendation.updateFocus) {
      lines.push(`- ${item}`);
    }
    lines.push("");
  }

  if (result.recommendations.length === 0) {
    lines.push("No affected docs were detected from the current inputs.", "");
  }

  return lines.join("\n").trimEnd();
}
