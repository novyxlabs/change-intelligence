import { createServer } from "node:http";
import { createHmac, timingSafeEqual } from "node:crypto";

import { runAnalysis } from "./index.js";

function jsonResponse(response, statusCode, payload) {
  response.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  response.end(`${JSON.stringify(payload, null, 2)}\n`);
}

function verifySignature(secret, rawBody, header) {
  if (!secret) {
    return true;
  }

  if (!header?.startsWith("sha256=")) {
    return false;
  }

  const expected = Buffer.from(
    `sha256=${createHmac("sha256", secret).update(rawBody).digest("hex")}`,
    "utf8",
  );
  const received = Buffer.from(header, "utf8");

  return expected.length === received.length && timingSafeEqual(expected, received);
}

export async function processGitHubWebhook(rawBody, headerSignature, config = {}) {
  const docsRoot = config.docsRoot ?? process.env.DOCS_ROOT ?? "docs";
  const secret = config.webhookSecret ?? process.env.GITHUB_WEBHOOK_SECRET ?? "";

  if (!verifySignature(secret, rawBody, headerSignature)) {
    return {
      statusCode: 401,
      payload: { error: "Invalid signature" },
    };
  }

  const payload = JSON.parse(rawBody);
  const patch = payload.pull_request?.patch ?? payload.patch;

  if (!patch) {
    return {
      statusCode: 400,
      payload: {
        error: "Missing patch text. Provide pull_request.patch or patch in the payload.",
      },
    };
  }

  const analysis = await runAnalysis({
    docs: docsRoot,
    patch,
  });

  return {
    statusCode: 200,
    payload: {
      ok: true,
      action: payload.action ?? null,
      repository: payload.repository?.full_name ?? null,
      pullRequestNumber: payload.pull_request?.number ?? null,
      commentBody: buildComment(payload, analysis),
      recommendations: analysis.recommendations,
      summary: analysis.summary,
    },
  };
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => {
      body += chunk;
    });
    request.on("end", () => resolve(body));
    request.on("error", reject);
  });
}

function buildComment(payload, analysis) {
  const repository = payload.repository?.full_name ?? "unknown/repo";
  const prNumber = payload.pull_request?.number ?? "unknown";

  return [
    `## Change Intelligence`,
    "",
    `Repository: \`${repository}\``,
    `Pull request: #${prNumber}`,
    "",
    analysis.markdown,
  ].join("\n");
}

export function createAppServer(config = {}) {
  return createServer(async (request, response) => {
    if (request.method === "GET" && request.url === "/health") {
      jsonResponse(response, 200, { ok: true });
      return;
    }

    if (request.method !== "POST" || request.url !== "/webhooks/github") {
      jsonResponse(response, 404, { error: "Not found" });
      return;
    }

    try {
      const rawBody = await readBody(request);
      const result = await processGitHubWebhook(
        rawBody,
        request.headers["x-hub-signature-256"],
        config,
      );
      jsonResponse(response, result.statusCode, result.payload);
    } catch (error) {
      jsonResponse(response, 500, {
        error: "Analysis failed",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.PORT ?? 3030);
  const server = createAppServer();
  server.listen(port, "127.0.0.1", () => {
    process.stdout.write(`change-intelligence server listening on http://127.0.0.1:${port}\n`);
  });
}
