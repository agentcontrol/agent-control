import { describe, expect, it } from "vitest";

import { control } from "../src/control";

describe("control", () => {
  it("passes through wrapped function return value", async () => {
    const wrapped = control(async (value: string) => `echo:${value}`);

    await expect(wrapped("hello")).resolves.toBe("echo:hello");
  });
});
