#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SPEAKEASY_BIN="${SDK_ROOT}/.speakeasy/bin/speakeasy"
SPEC_PATH="${OPENAPI_SPEC_PATH:-${SDK_ROOT}/../../server/.generated/openapi.json}"
OVERLAY_GENERATOR="${SCRIPT_DIR}/generate-method-names-overlay.py"
OVERLAY_PATH="${SDK_ROOT}/overlays/method-names.overlay.yaml"
TMP_OUTPUT_DIR="${SDK_ROOT}/.speakeasy/tmp-generated"
TMP_SPEC_PATH="${TMP_OUTPUT_DIR}/openapi.with-overrides.json"
GENERATED_DIR="${SDK_ROOT}/src/generated"

if [[ ! -x "${SPEAKEASY_BIN}" ]]; then
  echo "Speakeasy CLI not found at ${SPEAKEASY_BIN}. Run: make speakeasy-install" >&2
  exit 1
fi

if [[ ! -f "${SPEC_PATH}" ]]; then
  echo "OpenAPI spec not found at ${SPEC_PATH}. Generate it with: make openapi-spec" >&2
  exit 1
fi

if [[ ! -f "${OVERLAY_GENERATOR}" ]]; then
  echo "Overlay generator not found at ${OVERLAY_GENERATOR}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to generate overlay at ${OVERLAY_PATH}" >&2
  exit 1
fi

python3 "${OVERLAY_GENERATOR}" \
  --schema "${SPEC_PATH}" \
  --out "${OVERLAY_PATH}"

rm -rf "${TMP_OUTPUT_DIR}"
mkdir -p "${TMP_OUTPUT_DIR}"
cp "${SDK_ROOT}/gen.yaml" "${TMP_OUTPUT_DIR}/gen.yaml"

"${SPEAKEASY_BIN}" --logLevel error overlay apply \
  --schema "${SPEC_PATH}" \
  --overlay "${OVERLAY_PATH}" \
  --strict \
  --out "${TMP_SPEC_PATH}"

"${SPEAKEASY_BIN}" --logLevel error generate sdk \
  --auto-yes \
  --lang typescript \
  --schema "${TMP_SPEC_PATH}" \
  --out "${TMP_OUTPUT_DIR}"

if [[ ! -d "${TMP_OUTPUT_DIR}/src" ]]; then
  echo "Expected generated source directory at ${TMP_OUTPUT_DIR}/src" >&2
  exit 1
fi

rm -rf "${GENERATED_DIR}"
mkdir -p "${GENERATED_DIR}"
rsync -a --delete "${TMP_OUTPUT_DIR}/src/" "${GENERATED_DIR}/"
rm -rf "${TMP_OUTPUT_DIR}"

# Speakeasy seeds hooks/registration.ts with @ts-expect-error, which fails
# strict typecheck when no hook is registered. Normalize to @ts-ignore so
# committed and regenerated output stay deterministic.
REGISTRATION_FILE="${GENERATED_DIR}/hooks/registration.ts"
if [[ -f "${REGISTRATION_FILE}" ]]; then
  perl -0pi -e 's/@ts-expect-error/@ts-ignore/g' "${REGISTRATION_FILE}"
fi

# Default initAgent conflict mode to overwrite for SDK ergonomics while
# keeping server-side API default as strict.
INIT_REQUEST_MODEL="${GENERATED_DIR}/models/init-agent-request.ts"
if [[ -f "${INIT_REQUEST_MODEL}" ]]; then
  perl -0pi -e 's/conflictMode: z\.optional\(ConflictMode\$outboundSchema\),/conflictMode: z._default(z.optional(ConflictMode\$outboundSchema), "overwrite"),/g' "${INIT_REQUEST_MODEL}"
fi

echo "Generated TypeScript client copied to ${GENERATED_DIR}"
