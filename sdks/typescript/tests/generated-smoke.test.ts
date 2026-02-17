import { existsSync, readFileSync } from "node:fs";
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

  it("generated entrypoint export specifiers map to generated sources", () => {
    const generatedRoot = path.resolve(__dirname, "../src/generated");
    const generatedIndex = path.resolve(generatedRoot, "index.ts");
    const source = readFileSync(generatedIndex, "utf8");

    const exportSpecifiers = [...source.matchAll(/from\s+"(\.[^"]+)";/g)].map((match) => match[1]);
    expect(exportSpecifiers.length).toBeGreaterThan(0);

    for (const specifier of exportSpecifiers) {
      const tsSourcePath = path.resolve(generatedRoot, specifier.replace(/\.js$/, ".ts"));
      expect(existsSync(tsSourcePath)).toBe(true);
    }
  });
});
