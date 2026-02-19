export type JsonPrimitive = string | number | boolean | null;

export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export interface JsonObject {
  [key: string]: JsonValue;
}

export type * from "./generated/lib/config";
export type * from "./generated/lib/sdks";
export type * from "./generated/models/index";
export type * from "./generated/models/operations/index";
