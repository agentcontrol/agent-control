#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${SDK_ROOT}/.speakeasy/bin"
BIN_PATH="${BIN_DIR}/speakeasy"
WORKFLOW_FILE="${SDK_ROOT}/.speakeasy/workflow.yaml"

if [[ -z "${SPEAKEASY_VERSION:-}" && -f "${WORKFLOW_FILE}" ]]; then
  SPEAKEASY_VERSION="$(awk '/^speakeasyVersion:/ {print $2; exit}' "${WORKFLOW_FILE}" | tr -d "\"'")"
fi

SPEAKEASY_VERSION="${SPEAKEASY_VERSION:-1.721.5-rc.0}"
if [[ "${SPEAKEASY_VERSION}" != v* ]]; then
  SPEAKEASY_VERSION="v${SPEAKEASY_VERSION}"
fi

if [[ -x "${BIN_PATH}" ]]; then
  CURRENT_VERSION="$("${BIN_PATH}" --version | head -n1 | awk '{print $NF}' || true)"
  DESIRED_WITHOUT_V="${SPEAKEASY_VERSION#v}"

  if [[ "${CURRENT_VERSION}" == "${SPEAKEASY_VERSION}" || "${CURRENT_VERSION}" == "${DESIRED_WITHOUT_V}" ]]; then
    echo "Speakeasy CLI already present at ${BIN_PATH}"
    exit 0
  fi
fi

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"

case "${ARCH_RAW}" in
  x86_64) ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *)
    echo "Unsupported architecture: ${ARCH_RAW}" >&2
    exit 1
    ;;
esac

ASSET="speakeasy_${OS}_${ARCH}.zip"
URL="https://github.com/speakeasy-api/speakeasy/releases/download/${SPEAKEASY_VERSION}/${ASSET}"

mkdir -p "${BIN_DIR}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

curl -fsSL "${URL}" -o "${TMP_DIR}/speakeasy.zip"
unzip -q "${TMP_DIR}/speakeasy.zip" -d "${TMP_DIR}"
install -m 0755 "${TMP_DIR}/speakeasy" "${BIN_PATH}"

echo "Installed Speakeasy CLI ${SPEAKEASY_VERSION} to ${BIN_PATH}"
