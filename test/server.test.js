import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import { readFile } from "node:fs/promises";
import { processGitHubWebhook } from "../src/server.js";

function sign(secret, body) {
  return `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
}

test("health endpoint responds", async () => {
  const patch = await readFile(new URL("./fixtures/sample.patch", import.meta.url), "utf8");
  const payload = JSON.stringify({
    repository: { full_name: "acme/app" },
    pull_request: { number: 1, patch },
  });
  const result = await processGitHubWebhook(payload, "", {
    docsRoot: new URL("./fixtures/repo/docs", import.meta.url),
  });

  assert.equal(result.statusCode, 200);
  assert.equal(result.payload.ok, true);
});

test("webhook returns comment body for pull request payload", async () => {
  const patch = await readFile(new URL("./fixtures/sample.patch", import.meta.url), "utf8");
  const secret = "dev-secret";
  const payload = JSON.stringify({
    action: "opened",
    repository: { full_name: "acme/app" },
    pull_request: {
      number: 42,
      title: "Add coupon support",
      patch,
    },
  });

  const result = await processGitHubWebhook(payload, sign(secret, payload), {
    docsRoot: new URL("./fixtures/repo/docs", import.meta.url),
    webhookSecret: secret,
  });

  assert.equal(result.statusCode, 200);
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.pullRequestNumber, 42);
  assert.match(result.payload.commentBody, /billing\.md/);
  assert.equal(result.payload.recommendations[0].relativePath, "billing.md");
});

test("webhook rejects invalid signature", async () => {
  const patch = await readFile(new URL("./fixtures/sample.patch", import.meta.url), "utf8");
  const payload = JSON.stringify({
    repository: { full_name: "acme/app" },
    pull_request: { number: 9, patch },
  });

  const result = await processGitHubWebhook(payload, sign("wrong-secret", payload), {
    docsRoot: new URL("./fixtures/repo/docs", import.meta.url),
    webhookSecret: "real-secret",
  });

  assert.equal(result.statusCode, 401);
});
