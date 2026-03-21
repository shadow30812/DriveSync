IGNORED_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

IGNORED_EXTENSIONS = {".o", ".pyc", ".class", ".tmp", ".bak", ".swp"}

IGNORED_PREFIXES = {
    ".",
    "~$",
    "~",
}

INCLUDED_FILES = {".gitignore"}


def should_ignore(file_name):
    if file_name in IGNORED_NAMES:
        return True

    if (
        any(file_name.endswith(ext) for ext in IGNORED_EXTENSIONS)
        and file_name not in INCLUDED_FILES
    ):
        return True

    if (
        any(file_name.startswith(prefix) for prefix in IGNORED_PREFIXES)
        and file_name not in INCLUDED_FILES
    ):
        return True

    return False
