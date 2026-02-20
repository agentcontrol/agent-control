"""Generate OpenAPI specification for multi-language SDK generation."""

import argparse
import json
from pathlib import Path

from agent_control_server.main import app


def generate_openapi_spec(output_path: str = "server/.generated/openapi.json") -> None:
    """
    Generate OpenAPI specification file.

    This spec can be used to generate SDKs for multiple languages using tools like:
    - openapi-generator (supports 50+ languages)
    - swagger-codegen
    - Language-specific generators (typescript-axios, go-client, etc.)

    Args:
        output_path: Path where the OpenAPI spec should be saved
    """
    openapi_schema = app.openapi()

    # Add additional metadata for SDK generation
    openapi_schema["info"]["x-sdk-settings"] = {
        "packageName": "agent-control-sdk",
        "projectName": "agent-control",
    }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(openapi_schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"✓ OpenAPI spec generated: {output_file.absolute()}")
    print(f"  Version: {openapi_schema['info']['version']}")
    print(f"  Title: {openapi_schema['info']['title']}")
    print("\nUse this spec to generate SDKs:")
    print("  TypeScript (Speakeasy): make sdk-ts-generate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate OpenAPI specification.")
    parser.add_argument(
        "--output",
        default="server/.generated/openapi.json",
        help="Path where the OpenAPI spec should be saved.",
    )
    args = parser.parse_args()

    generate_openapi_spec(output_path=args.output)
