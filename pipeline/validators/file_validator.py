from pathlib import Path
from typing import Set, Union

SUPPORTED_EXTENSIONS: Set[str] = {".csv", ".json", ".xlsx", ".xls"}


def validate_file(file_path: Union[str, Path]) -> bool:
    """Validate that a given path exists, is a regular file, and has a supported extension.

    Supported extensions: .csv, .json, .xlsx, .xls

    Args:
        file_path (Union[str, Path]): Path to the file to be validated.

    Returns:
        bool: True if the file is valid.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the path is not a regular file or has an unsupported extension.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found at: {file_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a regular file: {file_path}")

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{path.suffix}'. "
            f"Supported extensions are: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    return True
