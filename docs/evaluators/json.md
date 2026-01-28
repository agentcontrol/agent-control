# JSON Evaluator Quickstart Guide

A practical guide for configuring JSON validation controls for LLM outputs and tool steps.

---

## What is the JSON Evaluator?

The JSON Validator Evaluator validates JSON data from LLM responses and tool steps before they're used or executed. It acts as a quality and safety layer, ensuring structured outputs meet your requirements, preventing malformed data, and enforcing business rules.

**Technical Foundation**: Uses [jsonschema](https://python-jsonschema.readthedocs.io/) for JSON Schema validation (Draft 7+) with custom field-level validators for simpler checks.

> **💡 JSON Schema vs Field-Level Validation**
>
> **JSON Schema can handle ALL the validation checks** this evaluator provides:
> - Required fields → `"required": ["field1"]`
> - Type checking → `"type": "string"`
> - Numeric ranges → `"minimum": 0, "maximum": 100`
> - Enum values → `"enum": ["active", "inactive"]`
> - String length → `"minLength": 3, "maxLength": 20`
> - Pattern matching → `"pattern": "^[a-z]+$"`
>
> **So why use field-level options?**
> - ✅ **Simpler** - No need to learn JSON Schema syntax
> - ✅ **Clearer** - More readable for simple validations
> - ✅ **Faster to write** - Less boilerplate for common checks
>
> **When to use JSON Schema:**
> - Complex nested structures (objects within objects)
> - Array validation (validate each item)
> - Cross-field dependencies
> - When you're already familiar with JSON Schema
>
> **When to use field-level options:**
> - Simple validations (types, ranges, enums)
> - You don't know JSON Schema
> - Quick checks without learning new syntax

> **💡 Performance Note**
>
> Uses Google RE2 regex engine for pattern matching, which is safe from ReDoS attacks but has some limitations:
> - ❌ No backreferences: `(foo|bar)\1`
> - ❌ No lookahead/lookbehind: `(?=foo)`, `(?<=bar)`
> - ✅ All common patterns: `[a-z]`, `[0-9]`, `\w`, `\d`, `\s`, `^`, `$`, `*`, `+`, `{n}`, etc.

**Key Benefits:**
- **Data Quality**: Ensure LLM outputs have correct structure and types
- **API Safety**: Prevent malformed data from reaching downstream systems
- **Business Rules**: Validate field values meet domain requirements
- **Security**: Block unexpected or dangerous data patterns
- **LLM Feedback Loops**: Clear error messages enable automatic retry and self-correction
- **Debugging**: Clear error messages pinpoint validation failures

**When to use:** Any application where LLM outputs or tool step input needs validation before use, especially in production with business-critical data or API integrations.

**Common Use Cases:**
- **Structured LLM Outputs**: Ensure LLMs return properly formatted JSON responses matching API contracts
- **LLM Self-Correction**: Feed validation errors back to LLM for automatic retry and correction
- **Tool Input Validation**: Block tool steps with invalid parameters before execution
- **Multi-Tenant Apps**: Validate tenant_id is always present to prevent data leakage
- **API Integrations**: Verify data conforms to third-party API schemas
- **Form Validation**: Ensure user data meets requirements (email format, age range, etc.)
- **Data Pipelines**: Validate intermediate data structures before processing
- **Configuration Validation**: Ensure config files have required fields and valid values

---

## Configuration Options

The JSON Validator evaluates data in this order:

1. **Syntax** - JSON must be valid (always enabled, controlled by `allow_invalid_json`)
2. **JSON Schema** - Comprehensive structure validation
3. **Required Fields** - Ensure critical fields exist
4. **Type Checking** - Validate field data types
5. **Field Constraints** - Numeric ranges, enums, string length
6. **Pattern Matching** - Regex validation on field values

> **⚠️ Important: Validation Order**
>
> Checks execute in a fixed order (syntax → schema → required → types → constraints → patterns).
> You cannot change this order. Earlier checks run before later ones.

### 1. Required Fields

**What**: Ensure critical fields are present in the JSON data.

**When to use**:
- Block LLM outputs missing essential fields
- Enforce API contract requirements
- Validate all necessary data is provided before processing

**Configuration**:
```json
{
  "required_fields": ["user_id", "email", "timestamp"]
}
```

**`allow_null_required` explained:**

This controls whether `null` values are acceptable in required fields.

- `false` (default): `null` is treated as **missing** → validation FAILS
- `true`: `null` is treated as **present** → validation PASSES

**Example with `allow_null_required: false` (default):**
```json
// Config
{
  "required_fields": ["email"],
  "allow_null_required": false
}

// ❌ FAILS - null treated as missing
{"email": null}

// ✅ PASSES - field present with value
{"email": "user@example.com"}
```

**Example with `allow_null_required: true`:**
```json
// Config
{
  "required_fields": ["email"],
  "allow_null_required": true
}

// ✅ PASSES - field present (null is okay)
{"email": null}

// ✅ PASSES - field present with value
{"email": "user@example.com"}

// ❌ FAILS - field missing entirely
{}
```

---

### 2. Type Checking

**What**: Validate that fields have the correct JSON data types.

**When to use**:
- Ensure fields are the expected type before using them
- Prevent type errors in downstream code
- Catch LLM mistakes (e.g., returning string "123" instead of number 123)

**Configuration**:
```json
{
  "field_types": {
    "user_id": "string",
    "age": "integer",
    "score": "number",
    "is_active": "boolean",
    "tags": "array",
    "metadata": "object"
  }
}
```

**Valid type names**: `"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"object"`, `"null"`

**Example**: Block wrong types:
```json
{
  "field_types": {
    "id": "string",
    "age": "integer",
    "score": "number"
  }
}
```

---

### 3. Field Constraints

**What**: Validate field values meet specific requirements (numeric ranges, enum values, string length).

**When to use**:
- Ensure numeric values are within acceptable ranges
- Restrict fields to predefined sets of values
- Enforce minimum/maximum string lengths

**Available constraint options**:

| Constraint Key | Type | Description | Example Value |
|---|---|---|---|
| `min` | number | Minimum value for numeric fields | `0`, `-100`, `0.5` |
| `max` | number | Maximum value for numeric fields | `100`, `1.0`, `999.99` |
| `enum` | array | List of allowed values | `["active", "inactive"]`, `[1, 2, 3]` |
| `min_length` | integer | Minimum string length | `3`, `8`, `1` |
| `max_length` | integer | Maximum string length | `20`, `500`, `100` |

**Notes**:
- `min`/`max` apply only to numeric values (integers and floats)
- `enum` works with any JSON value type (strings, numbers, booleans)
- `min_length`/`max_length` apply only to string values
- Multiple constraints can be combined on the same field

**For more complex validation needs**: If the built-in constraint options are too limited for your use case, consider using **JSON Schema** (see section 1) which provides comprehensive validation capabilities including:
- Conditional validation (if/then/else)
- Array item validation (minItems, maxItems, uniqueItems)
- String format validation (email, uri, date-time, etc.)
- Property dependencies and pattern properties
- Custom error messages and nested schema composition

JSON Schema is the most powerful option and can handle arbitrarily complex validation logic.

#### Numeric Constraints

```json
{
  "field_constraints": {
    "score": {"min": 0.0, "max": 1.0},
    "age": {"min": 0, "max": 120},
    "quantity": {"min": 1}
  }
}
```

#### Enum Constraints

```json
{
  "field_constraints": {
    "status": {"enum": ["active", "pending", "completed", "cancelled"]},
    "priority": {"enum": ["low", "medium", "high"]}
  },
  "case_sensitive_enums": false
}
```

**Case sensitivity**:
- `case_sensitive_enums: true` (default): `"Active"` ≠ `"active"`
- `case_sensitive_enums: false`: `"Active"` = `"active"` = `"ACTIVE"`

#### String Length Constraints

```json
{
  "field_constraints": {
    "username": {"min_length": 3, "max_length": 20},
    "password": {"min_length": 8},
    "bio": {"max_length": 500}
  }
}
```

---

### 4. Pattern Matching

**What**: Validate field values match regex patterns (email format, phone numbers, etc.).

**When to use**:
- Validate email addresses, URLs, phone numbers
- Ensure specific formats (e.g., ISO dates, UUIDs)
- Custom business patterns (e.g., product codes)

**Configuration**:
```json
{
  "field_patterns": {
    "email": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
    "phone": "^\\+?[1-9]\\d{1,14}$"
  }
}
```

**With flags (case-insensitive)**:
```json
{
  "field_patterns": {
    "email": {
      "pattern": "^[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}$",
      "flags": ["IGNORECASE"]
    }
  }
}
```

**Pattern match logic**:
- `pattern_match_logic: "all"` (default): ALL patterns must match
- `pattern_match_logic: "any"`: At least ONE pattern must match

---

### 5. JSON Schema Validation

**What**: Comprehensive validation using JSON Schema (Draft 7+).

**When to use**:
- Complex nested structures
- Array validation (validate each item)
- Cross-field dependencies
- When you're familiar with JSON Schema

**Configuration**:
```json
{
  "json_schema": {
    "type": "object",
    "required": ["action", "parameters"],
    "properties": {
      "action": {
        "type": "string",
        "enum": ["create", "update", "delete"]
      },
      "parameters": {
        "type": "object",
        "required": ["id"],
        "properties": {
          "id": {"type": "string"},
          "name": {"type": "string"},
          "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1
          }
        }
      }
    }
  }
}
```

---

## Common Scenarios

### Scenario 1: Basic Field Validation

Ensure LLM outputs have required fields with correct types.

```json
{
  "required_fields": ["user_id", "email", "status"],
  "field_types": {
    "user_id": "string",
    "email": "string",
    "status": "string"
  }
}
```

**Blocks**: Missing fields, wrong types
**Allows**: All required fields present with correct types

---

### Scenario 2: Read-Only API Validation

Validate LLM returns properly structured data with constrained values.

```json
{
  "required_fields": ["id", "score", "status"],
  "field_types": {
    "id": "string",
    "score": "number",
    "status": "string"
  },
  "field_constraints": {
    "score": {"min": 0.0, "max": 1.0},
    "status": {"enum": ["active", "pending", "completed"]}
  },
  "field_patterns": {
    "id": "^[a-zA-Z0-9-]{8,}$"
  }
}
```

**Blocks**: Missing fields, wrong types, scores outside [0,1], invalid status, malformed IDs
**Allows**: Properly structured data with valid types and values

---

### Scenario 3: Multi-Tenant Security

Ensure tenant_id is always present to prevent data leakage.

```json
{
  "required_fields": ["tenant_id"],
  "field_types": {
    "tenant_id": "string"
  },
  "field_constraints": {
    "tenant_id": {"min_length": 1}
  }
}
```

**Blocks**: Missing tenant_id, null tenant_id, empty tenant_id
**Allows**: Valid tenant_id present

---

### Scenario 4: Form Validation

Comprehensive validation for user input with business rules.

```json
{
  "required_fields": ["email", "username", "age"],
  "field_types": {
    "email": "string",
    "username": "string",
    "age": "integer"
  },
  "field_constraints": {
    "username": {"min_length": 3, "max_length": 20},
    "age": {"min": 13, "max": 120}
  },
  "field_patterns": {
    "email": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
  }
}
```

**Blocks**: Invalid email format, username too short/long, age outside range
**Allows**: Valid email, username, and age

---

## LLM Self-Correction with Validation Errors

One powerful use case for the JSON Validator is enabling **LLM retry loops** where validation errors are fed back to the LLM, allowing it to self-correct and try again.

### How It Works

1. **LLM generates response** → JSON output
2. **Evaluator validates** → Returns error if validation fails
3. **Error fed back to LLM** → Clear error message explains what's wrong
4. **LLM retries** → Generates corrected output
5. **Repeat** → Until validation passes or max retries reached

### Example: Self-Correcting LLM Output

**Initial LLM Response (validation fails):**
```json
{
  "user_id": 123,
  "age": "30",
  "status": "Running"
}
```

**Validation Error:**
```
Type validation failed: user_id: expected string, got integer; age: expected integer, got string
Constraint validation failed: status: value 'Running' not in allowed values: active, pending, completed
```

**LLM Retry with Error Feedback (validation passes):**
```json
{
  "user_id": "123",
  "age": 30,
  "status": "active"
}
```

### Implementation Pattern

```python
async def get_validated_llm_response(prompt, max_retries=3):
    for attempt in range(max_retries):
        # Get LLM response
        response = await llm.generate(prompt)

        # Validate (must await the async evaluate method)
        result = await json_validator.evaluate(response)

        # matched=False means validation PASSED
        if not result.matched:
            return response

        # Feed error back to LLM for retry
        prompt = f"{prompt}\n\nPrevious attempt failed validation:\n{result.message}\n\nPlease fix and try again."

    raise ValidationError("Max retries exceeded")
```

> **💡 Understanding the `matched` field**
>
> The `matched` field has inverted semantics:
> - `matched=False` → Validation **PASSED** (no validation rule was triggered)
> - `matched=True` → Validation **FAILED** (a validation rule was triggered)
>
> This is why we check `if not result.matched` to see if validation passed.

### Benefits

✅ **Self-correcting** - LLM learns from validation errors and fixes mistakes
✅ **Higher quality** - Ensures outputs meet requirements without human intervention
✅ **Production-ready** - Common pattern in production LLM applications
✅ **Clear feedback** - Detailed error messages guide the LLM to fix specific issues

### When to Use

- **Structured output generation** - Ensure LLM returns properly formatted data
- **API integration** - Validate LLM outputs before calling external APIs
- **Form filling** - Ensure LLM-generated form data meets all requirements
- **Data extraction** - Validate extracted data against expected schema

---

## Configuration Reference

Quick reference of all configuration options:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| **Validation Options** ||||
| `json_schema` | object | `null` | JSON Schema (Draft 7+) for comprehensive validation |
| `required_fields` | list[str] | `null` | List of required field paths (dot notation: `"user.id"`) |
| `field_types` | object | `null` | Map of field paths to JSON types (`"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"object"`, `"null"`) |
| `field_constraints` | object | `null` | Numeric ranges (`min`/`max`), enum values (`enum`), string length (`min_length`/`max_length`) |
| `field_patterns` | object | `null` | Regex patterns (string or dict with `"pattern"` and `"flags": ["IGNORECASE"]`) |
| **Behavior Options** ||||
| `allow_extra_fields` | bool | `true` | Allow fields beyond those in `field_types`. Set to `false` for strict validation |
| `allow_null_required` | bool | `false` | Treat `null` as present (vs missing) in required fields |
| `pattern_match_logic` | `"all"` \| `"any"` | `"all"` | All patterns must match or any pattern matches |
| `case_sensitive_enums` | bool | `true` | Case-sensitive enum matching. Set to `false` for case-insensitive |
| `allow_invalid_json` | bool | `false` | Allow invalid JSON through (don't block). Set to `true` for lenient parsing |

---

## Tips & Best Practices

✅ **Start simple, add complexity**
Begin with required fields and types, then add constraints and patterns as needed. This makes debugging easier.

✅ **Use JSON Schema for complex structures**
For nested objects, arrays, and cross-field dependencies, JSON Schema is more powerful than field-level checks.

✅ **Combine checks for defense-in-depth**
Use multiple validation strategies together (required + types + constraints) for comprehensive validation.

✅ **Test regex patterns before deployment**
- Use tools like [regex101.com](https://regex101.com) (set to RE2/Google mode)
- Remember RE2 limitations (no backreferences, lookahead, lookbehind)
- Keep patterns simple for better performance

✅ **Use dot notation for nested fields**
Access nested fields with `"user.profile.email"` instead of separate validators.

✅ **Consider case sensitivity**
- Default enum matching is case-sensitive
- Set `case_sensitive_enums: false` for flexible matching
- Use `flags: ["IGNORECASE"]` for case-insensitive patterns

✅ **Handle null values explicitly**
- Default: `null` in required fields = missing (validation fails)
- Set `allow_null_required: true` if you need to distinguish between `null` and missing
- Consider whether `null` should be allowed in your type checks

✅ **Understand validation order**
Checks run sequentially: **Syntax → Schema → Required → Types → Constraints → Patterns**

Earlier checks happen before later ones. A query blocked by required fields won't reach constraint checks.

---

## Troubleshooting

### Issue: "At least one validation check must be configured"

**Cause:** No validation options specified in config.

**Solution:** Add at least one of: `json_schema`, `required_fields`, `field_types`, `field_constraints`, or `field_patterns`.

```json
{
  "required_fields": ["id"]
}
```

---

### Issue: "Invalid type 'float' for field 'score'"

**Cause:** Used `"float"` as a type name. JSON only has `"number"` and `"integer"`.

**Solution:** Use `"number"` for floats and integers, or `"integer"` for integers only.

```json
{
  "field_types": {
    "score": "number",
    "count": "integer"
  }
}
```

---

### Issue: Pattern doesn't match expected values

**Cause:** RE2 regex syntax differences or incorrect JSON escaping.

**Solutions:**
1. Test pattern with RE2 specifically (not standard regex)
2. Escape backslashes in JSON: `"\\d"` not `"\d"`
3. Check for unsupported features (backreferences, lookahead)

```json
{
  "field_patterns": {
    "phone": "^\\+?[1-9]\\d{1,14}$"
  }
}
```

---

### Issue: "Field not found" errors for nested fields

**Cause:** Incorrect dot notation path or missing intermediate objects.

**Solution:** Verify JSON structure and use correct paths.

```json
// For {"user": {"profile": {"email": "test@example.com"}}}
{
  "required_fields": ["user.profile.email"]
}

// NOT: ["profile.email"] or ["user.email"]
```

---

### Issue: Enum matching fails with different case

**Cause:** Default enum matching is case-sensitive.

**Solution:** Set `case_sensitive_enums: false`.

```json
{
  "field_constraints": {
    "status": {"enum": ["active", "inactive"]}
  },
  "case_sensitive_enums": false
}
```

Now `"Active"`, `"ACTIVE"`, and `"active"` all match.

---

### Error Messages

**Parse Errors:**
- `"Invalid JSON: Expecting ',' delimiter: line 1 column 15"`
- `"Input data is None"`

**Schema Validation:**
- `"Schema validation failed: root: 'id' is a required property"`
- `"Schema validation failed: action: 'invalid' is not one of ['create', 'update', 'delete']"`

**Required Fields:**
- `"Missing required fields: user_id, email"`
- `"Missing required fields: status (null not allowed)"`

**Type Errors:**
- `"Type validation failed: age: expected integer, got string"`

**Constraint Errors:**
- `"Constraint validation failed: score: value 1.5 above maximum 1.0"`
- `"Constraint validation failed: status: value 'invalid' not in allowed values: active, pending"`

**Pattern Errors:**
- `"Pattern validation failed: email: pattern did not match"`

---

## Limitations

### Array Validation

Limited support for validating individual array elements with field-level options.

**Workaround**: Use JSON Schema for array validation:
```json
{
  "json_schema": {
    "type": "object",
    "properties": {
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "maxItems": 10
      }
    }
  }
}
```

### Regex Limitations (RE2)

RE2 doesn't support all regex features:
- ❌ Backreferences: `(foo|bar)\1`
- ❌ Lookahead/lookbehind: `(?=foo)`, `(?<=bar)`
- ✅ Character classes, quantifiers, anchors, groups

### Validation Order

Checks execute in fixed order (cannot be changed).

---

## See Also

- **regex evaluator** - Simple pattern matching without JSON structure validation
- **list evaluator** - Check if values are in/not in a list
- [JSON Schema specification](https://json-schema.org/draft-07/schema)
- [RE2 syntax](https://github.com/google/re2/wiki/Syntax)

---

**Evaluator Version:** 1.0.0
**Timeout:** 15 seconds (default)
**Thread Safe:** Yes
**ReDoS Safe:** Yes (uses RE2)
