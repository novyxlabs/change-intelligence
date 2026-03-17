import { readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export async function loadDiff(options) {
  if (options.patch) {
    return options.patch;
  }

  if (options.diff) {
    return readFile(options.diff, "utf8");
  }

  if (options.repo) {
    const { stdout } = await execFileAsync(
      "git",
      ["-C", options.repo, "diff", "--unified=0", options.base ?? "HEAD"],
      { maxBuffer: 1024 * 1024 * 4 },
    );
    return stdout;
  }

  throw new Error("Provide either --diff <file> or --repo <path>.");
}
