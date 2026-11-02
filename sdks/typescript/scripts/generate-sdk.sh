#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SPEAKEASY_BIN="${SDK_ROOT}/.speakeasy/bin/speakeasy"
SPEC_PATH="${OPENAPI_SPEC_PATH:-${SDK_ROOT}/../../server/.generated/openapi.json}"
OVERLAY_GENERATOR="${SCRIPT_DIR}/generate-method-names-overlay.py"
NORMALIZE_GENERATOR="${SCRIPT_DIR}/normalize_generated_sdk.py"
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

if [[ ! -f "${NORMALIZE_GENERATOR}" ]]; then
  echo "Generated SDK normalizer not found at ${NORMALIZE_GENERATOR}" >&2
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

# Speakeasy's empty hook-registration scaffold varies by generator account.
# It is not part of the client API, so drop it when it contains only the
# generated placeholder to keep checked-in output deterministic.
REGISTRATION_FILE="${GENERATED_DIR}/hooks/registration.ts"
HOOKS_FILE="${GENERATED_DIR}/hooks/hooks.ts"
if [[ -f "${REGISTRATION_FILE}" ]] && \
  grep -Fq 'Add hooks by calling hooks.register' "${REGISTRATION_FILE}" && \
  ! grep -Eq '^[[:space:]]+hooks\.register[A-Za-z]+Hook\(' "${REGISTRATION_FILE}"; then
  rm "${REGISTRATION_FILE}"
  perl -0pi -e 's/\nimport \{ initHooks \} from "\.\/registration\.js";\n//; s/\n[[:space:]]*initHooks\(this\);\n/\n/' "${HOOKS_FILE}"
fi

# Default initAgent conflict mode to overwrite for SDK ergonomics while
# keeping server-side API default as strict.
INIT_REQUEST_MODEL="${GENERATED_DIR}/models/init-agent-request.ts"
if [[ -f "${INIT_REQUEST_MODEL}" ]]; then
  perl -0pi -e 's/conflictMode: z\.optional\(ConflictMode\$outboundSchema\),/conflictMode: z._default(z.optional(ConflictMode\$outboundSchema), "overwrite"),/g' "${INIT_REQUEST_MODEL}"
fi

python3 "${NORMALIZE_GENERATOR}" \
  --schema "${SPEC_PATH}" \
  --generated-dir "${GENERATED_DIR}"

echo "Generated TypeScript client copied to ${GENERATED_DIR}"
