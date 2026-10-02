"""Load a local .env file into the process environment.

Keeping credentials in one ignored file beats exporting them into every shell.
Standard library only, so there is no python-dotenv dependency.

Real environment variables always win, so an export still overrides the file.
`.env` is already covered by the repository's .gitignore.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / ".env"


def load(path: Path | str = DEFAULT_PATH) -> list[str]:
    """Read KEY=value lines into os.environ without overwriting what is set.

    Args:
        path: The file to read. Missing files are ignored.

    Returns:
        The names that were loaded from the file.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return []

    loaded: list[str] = []
    for raw_line in file_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
