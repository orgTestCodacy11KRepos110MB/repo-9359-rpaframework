import logging
import os
import shutil
import time
from pathlib import Path
from typing import NamedTuple

from robot.libraries.BuiltIn import BuiltIn


class TimeoutException(Exception):
    """Exception raised from wait-prefixed keywords"""


class File(NamedTuple):
    """Robot Framework -friendly container for files."""

    path: str
    name: str
    size: int
    mtime: str

    def __str__(self):
        return self.path

    def __fspath__(self):
        # os.PathLike interface
        return self.path

    @classmethod
    def from_path(cls, path):
        """Create a File object from pathlib.Path or a path string."""
        path = Path(path)
        stat = path.stat()
        return cls(
            path=str(path.resolve()),
            name=path.name,
            size=stat.st_size,
            mtime=stat.st_mtime,
        )


class Directory(NamedTuple):
    """Robot Framework -friendly container for directories."""

    path: str
    name: str

    def __str__(self):
        return self.path

    def __fspath__(self):
        # os.PathLike interface
        return self.path

    @classmethod
    def from_path(cls, path):
        """Create a directory object from pathlib.Path or a path string."""
        path = Path(path)
        return cls(str(path.resolve()), path.name)


class FileSystem:
    """`FileSystem` is a library for finding, creating, and modifying
    files on a local filesystem.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    ROBOT_LIBRARY_DOC_FORMAT = "REST"

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def find_files(self, pattern, include_dirs=True, include_files=True):
        """Find files recursively according to a pattern.

        The ``pattern`` argument should be in glob format.
        Examples of valid patterns are ``*.xls`` or ``**/orders.txt``.

        With the options ``ìnclude_dirs`` and ``include_files``
        directories and files can be included/excluded from the results.

        Returns a list of paths that match the pattern.
        """
        pattern = Path(pattern)

        if pattern.is_absolute():
            root = Path(pattern.anchor)
            parts = pattern.parts[1:]
        else:
            root = Path.cwd()
            parts = pattern.parts

        pattern = str(Path(*parts))
        matches = []
        for path in root.glob(pattern):
            if path == root:
                continue

            if path.is_dir() and include_dirs:
                matches.append(Directory.from_path(path))
            elif path.is_file() and include_files:
                matches.append(File.from_path(path))

        return sorted(matches)

    def list_files_in_directory(self, path=None):
        """Lists all the files in the given directory, relative to it.

        If no path is given, uses current working directory.
        """
        return self.find_files(Path(path, "*"), include_dirs=False)

    def list_directories_in_directory(self, path=None):
        """Lists all the directories in the given directory, relative to it.

        If no path is given, uses current working directory.
        """
        return self.find_files(Path(path, "*"), include_files=False)

    def log_directory_tree(self, path=None):
        """Logs all the files in the directory recursively.

        If no path is given, uses current working directory.
        """
        root = Path(path) if path else Path.cwd()
        files = self.find_files(Path(root, "**/*"))

        rows = []
        previous = None
        for current in files:
            current = Path(current)
            if previous is None:
                shared = root
            elif previous == current.parent:
                shared = previous
            else:
                shared = set(previous.parents) & set(current.parents)
                shared = max(shared) if shared else root
            previous = current

            indent = "  " * len(shared.parts)
            relative = current.relative_to(shared)
            rows.append(f"{indent}{relative}")

        self.logger.info("\n".join(rows))

    def does_file_exist(self, path):
        """Returns True if the given file exists, False if not."""
        return bool(self.find_files(path, include_dirs=False))

    def does_file_not_exist(self, path):
        """Returns True if the file does not exist, False if it does."""
        return not self.does_file_exist(path)

    def does_directory_exist(self, path):
        """Returns True if the given directory exists, False if not."""
        return bool(self.find_files(path, include_files=False))

    def does_directory_not_exist(self, path):
        """Returns True if the directory does not exist, False if it does."""
        return not self.does_directory_exist(path)

    def is_directory_empty(self, path=None):
        """Returns True if the given directory has no files or subdirectories."""
        if self.does_directory_not_exist(path):
            raise NotADirectoryError(f"Not a valid directory: {path}")

        return not bool(self.find_files(Path(path, "*")))

    def is_directory_not_empty(self, path=None):
        """Returns True if the given directory has any files or subdirectories."""
        return not self.is_directory_empty(path)

    def is_file_empty(self, path):
        """Returns True if the given file has no content, i.e. has zero size."""
        if self.does_file_not_exist(path):
            raise FileNotFoundError(f"Not a valid file: {path}")
        path = Path(path)
        return path.stat().st_size == 0

    def is_file_not_empty(self, path):
        """Returns True if the given file has content, i.e. larger than zero size."""
        return not self.is_file_empty(path)

    def read_file(self, path, encoding="utf-8"):
        """Reads a file as text, with given `encoding`, and returns the content."""
        with open(path, "r", encoding=encoding) as fd:
            return fd.read()

    def read_binary_file(self, path):
        """Reads a file in binary mode and returns the content.
        Does not attempt to decode the content in any way.
        """
        with open(path, "rb") as fd:
            return fd.read()

    def touch_file(self, path):
        """Creates a file with no content, or if file already exists,
        updates the modification and access times.
        """
        Path(path).touch()

    def create_file(self, path, content=None, encoding="utf-8", overwrite=False):
        """Creates a new text file, and writes content if any is given.

        If the ``overwrite`` argument is truthy, the destination file is
        replaced if it already exists.
        """
        if not overwrite and Path(path).exists():
            raise FileExistsError(f"Path already exists: {path}")

        with open(path, "w", encoding=encoding) as fd:
            if content:
                fd.write(content)

    def create_binary_file(self, path, content=None, overwrite=False):
        """Creates a new binary file, and writes content if any is given.

        If the ``overwrite`` argument is truthy, the destination file is
        replaced if it already exists.
        """
        if not overwrite and Path(path).exists():
            raise FileExistsError(f"Path already exists: {path}")

        with open(path, "wb") as fd:
            if content:
                fd.write(content)

    def append_to_file(self, path, content, encoding="utf-8"):
        """Appends text to the given file."""
        if not Path(path).exists():
            raise FileNotFoundError(f"File does not exist: {path}")

        with open(path, "a", encoding=encoding) as fd:
            fd.write(content)

    def append_to_binary_file(self, path, content):
        """Appends binary content to the given file."""
        if not Path(path).exists():
            raise FileNotFoundError(f"File does not exist: {path}")

        with open(path, "ab") as fd:
            fd.write(content)

    def create_directory(self, path, parents=False, exist_ok=True):
        """Creates a directory and (optionally) non-existing parent directories.

        If the ``exist_ok`` argument is truthy, does not raise
        an error if the directory already exists.
        """
        Path(path).mkdir(parents=parents, exist_ok=exist_ok)

    def remove_file(self, path, missing_ok=True):
        """Removes the given file.

        If the ``missing_ok`` argument is truthy, does not raise
        an error if the file does not exist.
        """
        try:
            Path(path).unlink()
        except FileNotFoundError:
            if not missing_ok:
                raise

    def remove_files(self, *paths, missing_ok=True):
        """Removes multiple files.

        If the ``missing_ok`` argument is truthy, does not raise
        an error if any of the files do not exist.
        """
        # TODO: glob support
        for path in paths:
            self.remove_file(path, missing_ok=missing_ok)

    def remove_directory(self, path, recursive=False):
        """Removes the given directory, and optionally everything it contains."""
        if recursive:
            shutil.rmtree(str(path))
        else:
            Path(path).rmdir()

    def empty_directory(self, path):
        """Removes all the files in the given directory."""
        # TODO: Should it remove all subdirectories too?
        for item in self.list_files_in_directory(path):
            filepath = Path(path, item.name)
            self.remove_file(filepath)
            self.logger.info("Removed file: %s", filepath)

    def copy_file(self, source, destination):
        """Copy a file from source path to destination path."""
        src = Path(source)
        dst = Path(destination)

        if not src.is_file():
            raise FileNotFoundError(f"Source '{src}' is not a file")

        shutil.copyfile(src, dst)
        self.logger.info("Copied file: %s -> %s", src, dst)

    def copy_files(self, sources, destination):
        """Copy multiple files to destination folder.

        The ``sources`` argument is a list of files, and the
        ``destination`` argument is a directory.
        """
        # TODO: glob support
        dst_dir = Path(destination)

        if not dst_dir.is_dir():
            raise NotADirectoryError(f"Destination '{dst_dir}' is not a directory")

        for src in sources:
            name = src.name if isinstance(src, File) else Path(src).name
            dst = Path(dst_dir, name)
            self.copy_file(src, dst)

    def copy_directory(self, source, destination):
        """Copy directory from source path to destination path."""
        src = Path(source)
        dst = Path(destination)

        if not src.is_dir():
            raise NotADirectoryError(f"Source {src} is not a directory")
        if dst.exists():
            raise FileExistsError(f"Destination {dst} already exists")

        shutil.copytree(src, dst)

    def move_file(self, source, destination, overwrite=False):
        """Move a file from source path to destination path,
        optionally overwriting the destination.
        """
        src = Path(source)
        dst = Path(destination)

        if not src.is_file():
            raise FileNotFoundError(f"Source {src} is not a file")
        if dst.exists() and not overwrite:
            raise FileExistsError(f"Destination {dst} already exists")

        src.replace(dst)
        self.logger.info("Moved file: %s -> %s", src, dst)

    def move_files(self, sources, destination, overwrite=False):
        """Move multiple files to the destination folder.

        The ``sources`` argument is a list of files, and the
        ``destination`` argument is a directory.

        If the ``overwrite`` argument is truthy, overwrites any
        overlapping files in the destination directory.
        """
        dst_dir = Path(destination)

        if not dst_dir.is_dir():
            raise NotADirectoryError(f"Destination '{dst_dir}' is not a directory")

        for src in sources:
            dst = Path(dst_dir, Path(src).name)
            self.move_file(str(src), dst, overwrite)

    def move_directory(self, source, destination, overwrite=False):
        """Move a directory from source path to destination path.

        If the ``overwrite`` argument is truthy, overwrites the destination
        directory if it already exists.
        """
        src = Path(source)
        dst = Path(destination)

        if not src.is_dir():
            raise NotADirectoryError(f"Source {src} is not a directory")
        if dst.exists() and not overwrite:
            raise FileExistsError(f"Destination {dst} already exists")

        src.replace(dst)

    def change_file_extension(self, path, extension):
        """Replaces file extension for file at given path."""
        dst = Path(path).with_suffix(extension)
        self.move_file(path, dst)

    def join_path(self, *parts):
        """Joins multiple parts of a path together."""
        parts = [str(part) for part in parts]
        return str(Path(*parts))

    def absolute_path(self, path):
        """Returns the absolute path to a file, and resolves symlinks."""
        return str(Path(path).resolve())

    def normalize_path(self, path):
        """Removes redundant separators or up-level references from path."""
        return str(os.path.normpath(Path(path)))

    def get_file_name(self, path):
        """Returns only the filename portion of a path."""
        return str(Path(path).name)

    def get_file_extension(self, path):
        """Returns the suffix for the file."""
        return Path(path).suffix

    def get_file_modified_date(self, path):
        """Returns the modified time in seconds."""
        # TODO: Convert to proper date
        return Path(path).stat().st_mtime

    def get_file_creation_date(self, path):
        """Returns the creation time in seconds.

        Note: Linux sets this whenever file metadata changes
        """
        # TODO: Convert to proper date
        return Path(path).stat().st_ctime

    def get_file_size(self, path):
        """Returns the file size in bytes."""
        # TODO: Convert to human-friendly?
        return Path(path).stat().st_size

    def _wait_file(self, path, condition, timeout):
        """Poll file with `condition` callback until it returns True,
        or timeout is reached.
        """
        path = Path(path)
        end_time = time.time() + float(timeout)
        while time.time() < end_time:
            if condition(path):
                return True
            time.sleep(0.1)
        return False

    def wait_until_created(self, path, timeout=5.0):
        """Poll path until it exists, or raise exception if timeout
        is reached.
        """
        if not self._wait_file(path, lambda p: p.exists(), timeout):
            raise TimeoutException("Path was not created within timeout")

        return File.from_path(path)

    def wait_until_modified(self, path, timeout=5.0):
        """Poll path until it has been modified after the keyword was called,
        or raise exception if timeout is reached.
        """
        now = time.time()
        if not self._wait_file(path, lambda p: p.stat().st_mtime >= now, timeout):
            raise TimeoutException("Path was not modified within timeout")

        return File.from_path(path)

    def wait_until_removed(self, path, timeout=5.0):
        """Poll path until it doesn't exist, or raise exception if timeout
        is reached.
        """
        if not self._wait_file(path, lambda p: not p.exists(), timeout):
            raise TimeoutException("Path was not removed within timeout")

    def run_keyword_if_file_exists(self, path, keyword, *args):
        """If file exists at `path`, execute given keyword with arguments.

        Example:
        | Run keyword if file exists | orders.xlsx | Process orders |
        """
        if self.does_file_exist(path):
            return BuiltIn().run_keyword(keyword, *args)
        else:
            self.logger.info("File %s does not exist", path)
            return None