export function normalizeAnalysisOptions(options) {
  if (options.patch) {
    return {
      patch: options.patch,
      docs: options.docs,
    };
  }

  return options;
}
