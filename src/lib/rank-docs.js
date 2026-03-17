function intersectionSize(left, right) {
  let total = 0;
  for (const token of left) {
    if (right.has(token)) {
      total += 1;
    }
  }
  return total;
}

function containsInsensitive(haystack, needle) {
  return haystack.toLowerCase().includes(needle.toLowerCase());
}

export function rankDocuments(diff, docs) {
  const recommendations = [];

  for (const doc of docs) {
    let score = 0;
    const evidence = [];

    for (const file of diff.files) {
      const pathOverlap = intersectionSize(file.pathTokens, doc.tokens);
      const contentOverlap = intersectionSize(file.contentTokens, doc.tokens);

      if (containsInsensitive(doc.relativePath, file.basename)) {
        score += 6;
        evidence.push(`Path references changed file basename \`${file.basename}\``);
      }

      if (pathOverlap > 0) {
        score += pathOverlap * 2;
        evidence.push(
          `Shared path terms with \`${file.path}\`: ${[...file.pathTokens].filter((token) => doc.tokens.has(token)).slice(0, 5).join(", ")}`,
        );
      }

      if (contentOverlap > 0) {
        score += contentOverlap;
        evidence.push(
          `Shared change terms with \`${file.path}\`: ${[...file.contentTokens].filter((token) => doc.tokens.has(token)).slice(0, 5).join(", ")}`,
        );
      }
    }

    const matchingSymbols = [...diff.symbols].filter((symbol) =>
      doc.headings.some((heading) => containsInsensitive(heading, symbol)) ||
      containsInsensitive(doc.content, symbol),
    );

    if (matchingSymbols.length > 0) {
      score += matchingSymbols.length * 4;
      evidence.push(`Mentions changed symbols: ${matchingSymbols.slice(0, 5).join(", ")}`);
    }

    if (score === 0) {
      continue;
    }

    recommendations.push({
      path: doc.path,
      relativePath: doc.relativePath,
      score,
      evidence: [...new Set(evidence)].slice(0, 6),
      updateFocus: buildFocusAreas(doc, diff),
    });
  }

  return recommendations.sort((left, right) => right.score - left.score).slice(0, 10);
}

function buildFocusAreas(doc, diff) {
  const focus = [];

  for (const file of diff.files) {
    const overlappingTerms = [...file.contentTokens].filter((token) => doc.tokens.has(token));
    if (overlappingTerms.length === 0) {
      continue;
    }

    focus.push(
      `Review sections covering ${overlappingTerms.slice(0, 4).join(", ")} because \`${file.path}\` changed.`,
    );
  }

  if (focus.length === 0 && diff.symbols.size > 0) {
    focus.push(`Check references to changed symbols: ${[...diff.symbols].slice(0, 4).join(", ")}.`);
  }

  return [...new Set(focus)].slice(0, 3);
}
