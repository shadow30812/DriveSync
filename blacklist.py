IGNORED_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    ".vs",
    "packages",
    "bin",
    "obj",
    "Debug",
    "Release",
    ".DS_Store",
    "$RECYCLE.BIN",
    "System Volume Information",
    "Recovery",
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "ntuser.dat",
    "Thumbs.db",
    "ehthumbs.db",
    "desktop.ini",
}

IGNORED_EXTENSIONS = {
    ".o",
    ".d",
    ".pyc",
    ".class",
    ".tmp",
    ".bak",
    ".swp",
    ".obj",
    ".exe",
    ".dll",
    ".pdb",
    ".suo",
    ".user",
    ".lnk",
    ".dmp",
    ".log",
}

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
