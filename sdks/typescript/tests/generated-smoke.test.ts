import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe("generated client layout", () => {
  it("has a generated index entrypoint", () => {
    const generatedIndex = path.resolve(__dirname, "../src/generated/index.ts");
    expect(existsSync(generatedIndex)).toBe(true);
  });

  it("imports generated SDK entrypoint", async () => {
    const generated = await import("../src/generated/index");
    expect(typeof generated.AgentControlSDK).toBe("function");
  });
});
