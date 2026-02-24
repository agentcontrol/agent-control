#!/usr/bin/env python3
"""Generate a deterministic Speakeasy overlay for short SDK method names."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HTTP_METHOD_ORDER: tuple[str, ...] = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "trace",
)
HTTP_METHOD_RANK = {method: idx for idx, method in enumerate(HTTP_METHOD_ORDER)}
PREPOSITIONS = {"to", "from", "for", "in", "on", "of", "with", "by"}
VERB_RENAMES = {"patch": "update", "set": "update"}
METHOD_NAME_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("/api/v1/controls/{control_id}", "patch"): "updateMetadata",
}


@dataclass(frozen=True)
class Operation:
    path: str
    method: str
    group: str
    group_tokens: list[str]
    tokens: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate TypeScript method-name overlay from OpenAPI schema.",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to OpenAPI JSON schema.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Overlay YAML output path.",
    )
    return parser.parse_args()


def split_tokens(value: str) -> list[str]:
    raw_parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    tokens: list[str] = []
    for part in raw_parts:
        split_part = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part).split()
        tokens.extend(piece.lower() for piece in split_part if piece)
    return tokens


def singularize(token: str) -> str:
    if token.endswith("ies") and len(token) > 3:
        return f"{token[:-3]}y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 1:
        return token[:-1]
    return token


def pluralize(token: str) -> str:
    if token.endswith("y") and len(token) > 1 and token[-2] not in "aeiou":
        return f"{token[:-1]}ies"
    if token.endswith("s"):
        return token
    return f"{token}s"


def lower_camel(tokens: list[str]) -> str:
    if not tokens:
        return "call"
    first = tokens[0].lower()
    rest = "".join(token.capitalize() for token in tokens[1:])
    return f"{first}{rest}"


def infer_group(path: str, op: dict[str, object]) -> tuple[str, list[str]]:
    tags = op.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag:
                tag_tokens = split_tokens(tag)
                if tag_tokens:
                    return lower_camel(tag_tokens), tag_tokens

    path_tokens = [
        segment
        for segment in path.strip("/").split("/")
        if segment and not (segment.startswith("{") and segment.endswith("}"))
    ]
    for segment in path_tokens:
        if segment in {"api", "v1"}:
            continue
        segment_tokens = split_tokens(segment)
        if segment_tokens:
            return lower_camel(segment_tokens), segment_tokens
    return "system", ["system"]


def build_tokens(path: str, method: str, op: dict[str, object]) -> list[str]:
    raw_operation_id = op.get("operationId")
    if isinstance(raw_operation_id, str) and raw_operation_id:
        prefix = re.sub(r"_api_v\d+.*$", "", raw_operation_id)
        prefix = re.sub(r"_(get|post|put|patch|delete|options|head|trace)$", "", prefix)
        operation_tokens = split_tokens(prefix)
        if len(operation_tokens) >= 3 and operation_tokens[-1] == operation_tokens[0]:
            operation_tokens = operation_tokens[:-1]
        if operation_tokens:
            return operation_tokens

    path_tokens = []
    for segment in path.strip("/").split("/"):
        if not segment or (segment.startswith("{") and segment.endswith("}")):
            continue
        path_tokens.extend(split_tokens(segment))
    return [method, *path_tokens]


def build_group_forms(group_tokens: list[str]) -> tuple[set[str], set[str], set[str]]:
    forms: set[str] = set()
    singular_forms: set[str] = set()
    plural_forms: set[str] = set()
    for token in group_tokens:
        singular = singularize(token)
        plural = pluralize(singular)
        forms.add(token)
        forms.add(singular)
        forms.add(plural)
        singular_forms.add(singular)
        plural_forms.add(plural)
    return forms, singular_forms, plural_forms


def normalize_tokens(tokens: list[str]) -> list[str]:
    if not tokens:
        return ["call"]
    normalized = [token for token in tokens]
    normalized[0] = VERB_RENAMES.get(normalized[0], normalized[0])
    return normalized


def derive_name(
    tokens: list[str],
    group_forms: set[str],
    group_singular_forms: set[str],
    group_plural_forms: set[str],
    strip_group_tokens: bool,
) -> str:
    working = normalize_tokens(tokens)

    if (
        len(working) >= 2
        and working[0] == "get"
        and working[1] in group_plural_forms
        and working[1] not in group_singular_forms
    ):
        working = ["list", *working[2:]]

    if strip_group_tokens:
        while len(working) >= 2 and working[1] in group_forms:
            del working[1]
        if (
            len(working) >= 3
            and working[-2] in PREPOSITIONS
            and working[-1] in group_forms
        ):
            working = working[:-2]

    if not working:
        working = ["call"]

    candidate = lower_camel(working)
    if candidate[0].isdigit():
        candidate = f"op{candidate.capitalize()}"
    return candidate


def iter_operations(schema: dict[str, object]) -> list[Operation]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI schema is missing a valid 'paths' object.")

    operations: list[Operation] = []
    for path, methods in paths.items():
        if not isinstance(path, str) or not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if not isinstance(method, str):
                continue
            method_lower = method.lower()
            if method_lower not in HTTP_METHOD_RANK:
                continue
            if not isinstance(op, dict):
                continue
            group, group_tokens = infer_group(path, op)
            tokens = build_tokens(path, method_lower, op)
            operations.append(
                Operation(
                    path=path,
                    method=method_lower,
                    group=group,
                    group_tokens=group_tokens,
                    tokens=tokens,
                )
            )

    operations.sort(
        key=lambda op: (
            op.path,
            HTTP_METHOD_RANK[op.method],
        )
    )
    return operations


def resolve_names(operations: list[Operation]) -> dict[tuple[str, str], tuple[str, str]]:
    used_by_group: dict[str, set[str]] = defaultdict(set)
    resolved: dict[tuple[str, str], tuple[str, str]] = {}

    for op in operations:
        explicit_name = METHOD_NAME_EXCEPTIONS.get((op.path, op.method))
        if explicit_name is not None:
            names_for_group = used_by_group[op.group]
            if explicit_name in names_for_group:
                raise ValueError(
                    f"Exception name collision in group '{op.group}': {explicit_name}"
                )
            names_for_group.add(explicit_name)
            resolved[(op.path, op.method)] = (op.group, explicit_name)
            continue

        group_forms, singular_forms, plural_forms = build_group_forms(op.group_tokens)
        preferred = derive_name(
            op.tokens,
            group_forms,
            singular_forms,
            plural_forms,
            strip_group_tokens=True,
        )
        name = preferred
        used_names = used_by_group[op.group]

        if name in used_names:
            fallback = derive_name(
                op.tokens,
                group_forms,
                singular_forms,
                plural_forms,
                strip_group_tokens=False,
            )
            name = fallback

        if name in used_names:
            base = f"{name}{op.method.capitalize()}"
            name = base
            suffix = 2
            while name in used_names:
                name = f"{base}{suffix}"
                suffix += 1

        used_names.add(name)
        resolved[(op.path, op.method)] = (op.group, name)

    return resolved


def render_overlay(
    operations: list[Operation],
    names: dict[tuple[str, str], tuple[str, str]],
) -> str:
    lines = [
        "# AUTO-GENERATED by scripts/generate-method-names-overlay.py",
        "# Do not edit manually.",
        "overlay: 1.0.0",
        "info:",
        "  title: TypeScript SDK method naming overrides",
        "  version: 0.0.1",
        "actions:",
    ]

    for op in operations:
        group, method_name = names[(op.path, op.method)]
        escaped_path = op.path.replace('"', '\\"')
        lines.extend(
            [
                f'  - target: $["paths"]["{escaped_path}"]["{op.method}"]',
                "    update:",
                f"      x-speakeasy-group: {group}",
                f"      x-speakeasy-name-override: {method_name}",
                "",
            ]
        )

    if lines[-1] == "":
        lines.pop()
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    schema_path = Path(args.schema)
    output_path = Path(args.out)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    operations = iter_operations(schema)
    names = resolve_names(operations)
    overlay = render_overlay(operations, names)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(overlay, encoding="utf-8")


if __name__ == "__main__":
    main()
