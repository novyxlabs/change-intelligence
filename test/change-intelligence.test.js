import test from "node:test";
import assert from "node:assert/strict";

import { readFile } from "node:fs/promises";
import { parseUnifiedDiff } from "../src/lib/parse-diff.js";
import { indexDocs } from "../src/lib/index-docs.js";
import { rankDocuments } from "../src/lib/rank-docs.js";

test("extracts changed files and symbols from unified diff", async () => {
  const diff = await readFile(new URL("./fixtures/sample.patch", import.meta.url), "utf8");
  const parsed = parseUnifiedDiff(diff);

  assert.deepEqual(parsed.files.map((file) => file.path), ["src/billing/createCheckoutSession.ts"]);
  assert.ok(parsed.symbols.has("createCheckoutSession"));
});

test("ranks matching docs above unrelated docs", async () => {
  const diff = await readFile(new URL("./fixtures/sample.patch", import.meta.url), "utf8");
  const parsed = parseUnifiedDiff(diff);
  const docs = await indexDocs(new URL("./fixtures/repo/docs", import.meta.url));
  const recommendations = rankDocuments(parsed, docs);

  assert.equal(recommendations.length, 1);
  assert.equal(recommendations[0].relativePath, "billing.md");
  assert.ok(recommendations[0].score > 0);
});
