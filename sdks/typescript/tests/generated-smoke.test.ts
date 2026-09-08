import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { stepToJSON } from "../src/generated/models/step";

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

  it("serializes structured Step scorer context", () => {
    const serialized = stepToJSON({
      type: "llm",
      name: "answer",
      input: "question",
      output: "answer",
      groundTruth: "expected",
      tools: [
        {
          name: "search",
          description: "Search documents",
          input_schema: { type: "object" },
        },
      ],
    });

    expect(JSON.parse(serialized)).toEqual({
      type: "llm",
      name: "answer",
      input: "question",
      output: "answer",
      ground_truth: "expected",
      tools: [
        {
          name: "search",
          description: "Search documents",
          input_schema: { type: "object" },
        },
      ],
    });
  });
});
