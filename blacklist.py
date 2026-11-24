import os

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


IGNORED_DIR_NAMES = {
    "build",
    "target",
    "tinytex",
}

IGNORED_DIR_SUFFIXES = {
    ".build",
    ".dist",
    ".onefile-build",
    ".runs",
    ".cache",
    ".sim",
    ".hw",
    ".gen",
    ".ip_user_files",
}

IGNORED_DIR_PREFIXES = {
    "xpack-",
}

IGNORED_DIR_PATHS = {
    ("formal", "work"),
    ("riemann", "dist", "sessions"),
}

IGNORED_DIR_MARKERS = {
    "pyvenv.cfg",
    "CACHEDIR.TAG",
}

IGNORED_DIRS = {
    "/mnt/Windows/Well/EE docx/2nd yr UG/Spring Sem/AI_ML/Lab/Week 10/annotations",
}

INCLUDED_DIRS = {
    "/mnt/Windows/Well/Projects/SDE/riemann/riemann",
    "/mnt/Windows/Well/Projects/SDE/sentinel/build",
}

PROTECTED_DIRS = {
    "/mnt/Windows/Well/Projects/EE Core/tmp",
}

PROTECTED_JUNK_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    ".vs",
    ".Xil",
    ".pio",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

PROTECTED_JUNK_EXTENSIONS = {
    ".o",
    ".d",
    ".pyc",
    ".class",
    ".tmp",
    ".bak",
    ".swp",
    ".obj",
}

INCLUDED_FILE_PATHS = {
    "/mnt/Windows/Well/Projects/SDE/riemann/dist/Riemann",
    "/mnt/Windows/Well/Projects/SDE/riemann/dist/Riemann.exe",
    "/mnt/Windows/Well/Projects/SDE/riemann/dist/Riemann_ver_5dot1",
}


def should_ignore(file_name):
    if file_name in IGNORED_NAMES:
        return True

    if (
        any(file_name.endswith(ext) for ext in IGNORED_EXTENSIONS)
        and file_name not in INCLUDED_FILES
    ):
        return True

    return bool(
        any(file_name.startswith(prefix) for prefix in IGNORED_PREFIXES)
        and file_name not in INCLUDED_FILES
    )


def _is_under(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _is_protected(path):
    return _is_under(path, PROTECTED_DIRS)


def _is_protected_junk(name):
    return name in PROTECTED_JUNK_NAMES or any(
        name.endswith(ext) for ext in PROTECTED_JUNK_EXTENSIONS
    )


def _is_regenerable_dir(dir_path, name):
    if name in IGNORED_DIR_NAMES:
        return True
    if any(name.endswith(suffix) for suffix in IGNORED_DIR_SUFFIXES):
        return True
    if any(name.startswith(prefix) for prefix in IGNORED_DIR_PREFIXES):
        return True

    parts = tuple(dir_path.split(os.sep))
    if any(parts[-len(tail) :] == tail for tail in IGNORED_DIR_PATHS):
        return True

    return any(
        os.path.isfile(os.path.join(dir_path, marker)) for marker in IGNORED_DIR_MARKERS
    )


def should_ignore_file(file_path):
    """Full check for a file. Inside a protected tree only junk files
    (object files, editor/OS clutter) are skipped."""
    file_path = os.path.normpath(file_path)
    if file_path in INCLUDED_FILE_PATHS:
        return False

    name = os.path.basename(file_path)
    if _is_protected(file_path):
        return _is_protected_junk(name)
    return should_ignore(name)


def should_ignore_dir(dir_path):
    """Full check for a directory: name rules plus regenerable-folder rules.
    Inside a protected tree the generic name rules are replaced by the
    narrower junk list; regenerable-folder rules still apply. Inside an
    included tree only the name rules apply."""
    dir_path = os.path.normpath(dir_path)
    if dir_path in INCLUDED_DIRS or dir_path in PROTECTED_DIRS:
        return False

    if dir_path in IGNORED_DIRS:
        return True

    name = os.path.basename(dir_path)
    if _is_protected(dir_path):
        if _is_protected_junk(name):
            return True
    elif should_ignore(name):
        return True

    if _is_under(dir_path, INCLUDED_DIRS):
        return False
    return _is_regenerable_dir(dir_path, name)
