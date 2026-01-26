"""Generate OpenAPI specification for multi-language SDK generation."""

import json
from pathlib import Path

from agent_control_server.main import app


def generate_openapi_spec(output_path: str = "openapi.json") -> None:
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
    output_file.write_text(json.dumps(openapi_schema, indent=2))

    print(f"✓ OpenAPI spec generated: {output_file.absolute()}")
    print(f"  Version: {openapi_schema['info']['version']}")
    print(f"  Title: {openapi_schema['info']['title']}")
    print("\nUse this spec to generate SDKs:")
    print(f"  TypeScript: openapi-generator-cli generate -i {output_path} -g typescript-axios")
    print(f"  Go: openapi-generator-cli generate -i {output_path} -g go")
    print(f"  Rust: openapi-generator-cli generate -i {output_path} -g rust")


if __name__ == "__main__":
    generate_openapi_spec()

