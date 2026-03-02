import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("generated client layout", () => {
  it("has a generated index entrypoint", () => {
    const generatedIndex = path.resolve(process.cwd(), "src/generated/index.ts");
    expect(existsSync(generatedIndex)).toBe(true);
  });

  it("generated entrypoint export specifiers map to generated sources", () => {
    const generatedRoot = path.resolve(process.cwd(), "src/generated");
    const generatedIndex = path.resolve(generatedRoot, "index.ts");
    const source = readFileSync(generatedIndex, "utf8");

    const exportSpecifiers = [...source.matchAll(/from\s+"(\.[^"]+)";/g)].map((match) => match[1]);
    expect(exportSpecifiers.length).toBeGreaterThan(0);

    for (const specifier of exportSpecifiers) {
      const tsSourcePath = path.resolve(generatedRoot, specifier.replace(/\.js$/, ".ts"));
      if (!existsSync(tsSourcePath)) {
        throw new Error(`Generated source missing for export specifier '${specifier}': ${tsSourcePath}`);
      }
    }
  });
});
