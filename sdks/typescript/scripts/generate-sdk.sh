#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SPEAKEASY_BIN="${SDK_ROOT}/.speakeasy/bin/speakeasy"
SPEC_PATH="${SDK_ROOT}/../../server/openapi.json"
TMP_OUTPUT_DIR="${SDK_ROOT}/.speakeasy/tmp-generated"
GENERATED_DIR="${SDK_ROOT}/src/generated"

if [[ ! -x "${SPEAKEASY_BIN}" ]]; then
  echo "Speakeasy CLI not found at ${SPEAKEASY_BIN}. Run: make speakeasy-install" >&2
  exit 1
fi

if [[ ! -f "${SPEC_PATH}" ]]; then
  echo "OpenAPI spec not found at ${SPEC_PATH}. Run: make openapi-spec" >&2
  exit 1
fi

rm -rf "${TMP_OUTPUT_DIR}"
mkdir -p "${TMP_OUTPUT_DIR}"
cp "${SDK_ROOT}/gen.yaml" "${TMP_OUTPUT_DIR}/gen.yaml"

"${SPEAKEASY_BIN}" --logLevel error generate sdk \
  --auto-yes \
  --lang typescript \
  --schema "${SPEC_PATH}" \
  --out "${TMP_OUTPUT_DIR}"

if [[ ! -d "${TMP_OUTPUT_DIR}/src" ]]; then
  echo "Expected generated source directory at ${TMP_OUTPUT_DIR}/src" >&2
  exit 1
fi

rm -rf "${GENERATED_DIR}"
mkdir -p "${GENERATED_DIR}"
rsync -a --delete "${TMP_OUTPUT_DIR}/src/" "${GENERATED_DIR}/"
rm -rf "${TMP_OUTPUT_DIR}"

echo "Generated TypeScript client copied to ${GENERATED_DIR}"
