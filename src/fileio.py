"""Filesystem helpers and verified writes for Omega skills.

Verified write results use a disk read-back for the size, hash, and content
snippets. Write failures return an explicit *-FAILED result to the agent loop.
"""
import base64
import errno
import fcntl
import hashlib
import io
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

from src.logger import get_logger

logger = get_logger(__name__)

SNIPPET_BYTES = 80
HASH_MAX_BYTES = 2_000_000


def make_dirs(path) -> bool:
    """Create a directory and any missing parent directories."""
    path = str(path)
    try:
        os.makedirs(path, exist_ok=True)
    except (OSError, ValueError) as e:
        logger.error(f"[FILE_IO] mkdir failed path={path} err={e}")
        return False
    logger.info(f"[FILE_IO] mkdir ok path={path}")
    return True


def validate_file_or_folder_name(name) -> bool:
    """Accept one ASCII path segment with a leading letter or digit."""
    name = str(name)
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name)) and ".." not in name


def safe_subpath(base_dir, folder, *children) -> str:
    """Resolve validated segments strictly beneath their canonical parents.

    The caller supplies a trusted base. Missing path components are allowed so
    the result can also be used for directory creation and file writes.
    """
    base_dir = str(base_dir)
    if not base_dir:
        return ""

    try:
        parent = os.path.realpath(base_dir)
        for segment in (folder, *children):
            segment = str(segment)
            if not validate_file_or_folder_name(segment):
                return ""
            target = os.path.realpath(os.path.join(parent, segment))
            if target == parent or not target.startswith(parent.rstrip(os.sep) + os.sep):
                return ""
            parent = target
        return parent
    except (OSError, ValueError):
        return ""


def _relative_target(base, *segments):
    """Canonicalize local links, then walk the result from the pinned base."""
    target = safe_subpath(base, *segments)
    if not target:
        raise ValueError("unsafe path")
    parts = Path(target).relative_to(base).parts
    if not parts:
        raise ValueError("empty path")
    return target, parts


def _open_dirs(stack, parent_fd, parts, create=False):
    for part in parts:
        if create:
            try:
                os.mkdir(part, dir_fd=parent_fd)
            except FileExistsError:
                pass
        parent_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        stack.callback(os.close, parent_fd)
    return parent_fd


@contextmanager
def _workflow_directory(memory_dir, workflow_dir, *, create=False):
    if not str(memory_dir) or not str(workflow_dir):
        raise ValueError("empty memory or workflow directory")
    memory_path = Path(os.path.abspath(str(memory_dir)))
    workflow_path = Path(os.path.abspath(str(workflow_dir)))
    base = Path(os.path.realpath(memory_path, strict=True))
    if workflow_path.is_relative_to(memory_path):
        parts = workflow_path.relative_to(memory_path).parts
    else:
        # Paths can share a spelling such as /var even when the trusted root
        # itself is an alias. Resolve only ancestors shared with that root.
        shared = Path(os.path.commonpath((memory_path, workflow_path)))
        workflow_path = Path(os.path.realpath(shared, strict=True)) / workflow_path.relative_to(shared)
        parts = workflow_path.relative_to(base).parts
    if not parts:
        raise ValueError("workflow directory must be below the memory directory")

    with ExitStack() as stack:
        base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, base_fd)
        # Keep the workflow path lexical so no symlink below the memory root is followed.
        yield os.path.join(base, *parts), _open_dirs(stack, base_fd, parts, create)


def prepare_workflow_directory(memory_dir, workflow_dir) -> bool:
    try:
        with _workflow_directory(memory_dir, workflow_dir, create=True):
            return True
    except (OSError, ValueError) as exc:
        logger.error(f"[FILE_IO] workflow directory unavailable path={workflow_dir} err={exc}")
        return False


def research_directory(memory_dir, workflow_dir) -> str:
    try:
        with _workflow_directory(memory_dir, workflow_dir) as (base, fd), ExitStack() as stack:
            path, parts = _relative_target(base, "research")
            _open_dirs(stack, fd, parts)
            return path
    except (OSError, ValueError):
        return ""


@contextmanager
def _research_project(memory_dir, workflow_dir, project, *, create=False):
    with _workflow_directory(memory_dir, workflow_dir) as (base, fd), ExitStack() as stack:
        project_path, parts = _relative_target(base, "research", project)
        yield project_path, _open_dirs(stack, fd, parts, create)


@contextmanager
def _research_target(project_path, project_fd, filename):
    path, parts = _relative_target(project_path, *str(filename).split("/"))
    with ExitStack() as stack:
        parent_fd = _open_dirs(stack, project_fd, parts[:-1])
        yield path, parent_fd, parts[-1]


@contextmanager
def _regular_file(parent_fd, name, flags):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("expected a regular file")
        with os.fdopen(fd, "rb", buffering=0, closefd=False) as stream:
            yield stream
    finally:
        os.close(fd)


def _copy_access_acl(source_fd, target_fd):
    if sys.platform == "darwin":
        import ctypes

        copy_acl = ctypes.CDLL(None, use_errno=True).fcopyfile
        copy_acl.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
        copyfile_acl = 1  # COPYFILE_ACL in macOS copyfile.h
        if copy_acl(source_fd, target_fd, None, copyfile_acl) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return

    for attribute in ("system.posix_acl_access", "system.nfs4_acl"):
        try:
            acl = os.getxattr(source_fd, attribute)
        except OSError as exc:
            if exc.errno == errno.ENOTSUP:
                continue
            if exc.errno != errno.ENODATA:
                raise
            # The temporary file may have inherited an ACL from its parent.
            try:
                os.removexattr(target_fd, attribute)
            except OSError as removal:
                if removal.errno != errno.ENODATA:
                    raise
        else:
            os.setxattr(target_fd, attribute, acl)


def _replace_research_file(parent_fd, name, data, existing):
    temporary = f".research-{secrets.token_hex(16)}.tmp"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600 if existing else 0o666, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "w+b") as stream:
            stream.write(data)
            stream.flush()
            if existing:
                metadata = os.fstat(existing.fileno())
                staged = os.fstat(fd)
                if (staged.st_uid, staged.st_gid) != (metadata.st_uid, metadata.st_gid):
                    os.fchown(fd, metadata.st_uid, metadata.st_gid)
                os.fchmod(fd, metadata.st_mode & 0o777)
                _copy_access_acl(existing.fileno(), fd)
            os.fsync(fd)
            stream.seek(0)
            readback = _readback(stream)
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)
        raise
    return readback


def _overwrite_open_file(fd, source):
    with os.fdopen(fd, "r+b", closefd=False) as stream:
        stream.seek(0)
        shutil.copyfileobj(source, stream)
        stream.truncate()
        stream.flush()


def _update_existing_research_file(existing, parent_fd, name, data):
    fd = existing.fileno()
    metadata = os.fstat(fd)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if metadata.st_nlink != 1 or not os.path.samestat(metadata, current):
        raise OSError(errno.EBUSY, "Cannot update a replaced or multiply linked research file")

    with tempfile.TemporaryFile() as backup:
        existing.seek(0)
        shutil.copyfileobj(existing, backup)
        try:
            _overwrite_open_file(fd, io.BytesIO(data))
            os.fsync(fd)
            existing.seek(0)
            return _readback(existing)
        except OSError:
            try:
                backup.seek(0)
                _overwrite_open_file(fd, backup)
                os.fsync(fd)
            except OSError:
                logger.exception("[FILE_IO] failed to restore research file %s", name)
            raise


def _write_research_file(project_path, project_fd, filename, content):
    data = str(content).encode("utf-8")
    with _research_target(project_path, project_fd, filename) as (path, parent_fd, name), ExitStack() as stack:
        try:
            existing = stack.enter_context(_regular_file(parent_fd, name, os.O_RDWR))
        except FileNotFoundError:
            existing = None
        if existing is not None:
            fd = existing.fileno()
            fcntl.flock(fd, fcntl.LOCK_EX)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not os.path.samestat(os.fstat(fd), current):
                raise OSError(errno.EBUSY, "Research file was replaced during the write")
        try:
            readback = _replace_research_file(parent_fd, name, data, existing)
        except PermissionError:
            if existing is None:
                raise
            # Keeping the inode preserves permissions when replacement cannot.
            readback = _update_existing_research_file(existing, parent_fd, name, data)
        return _verified_result("WRITE", path, readback)


def write_research_file(memory_dir, workflow_dir, project, filename, content):
    try:
        with _research_project(memory_dir, workflow_dir, project) as (path, fd):
            return _write_research_file(path, fd, filename, content)
    except (OSError, ValueError) as exc:
        return f"WRITE-FAILED file={project}/{filename}: {exc}"


def start_research(memory_dir, workflow_dir, project, topic):
    try:
        with _research_project(memory_dir, workflow_dir, project, create=True) as (path, fd):
            for folder in ("src", "data", "runs", "figures"):
                _, parts = _relative_target(path, folder)
                with ExitStack() as stack:
                    _open_dirs(stack, fd, parts, create=True)
            try:
                _write_research_file(path, fd, "topic.txt", topic)
            except (OSError, UnicodeEncodeError) as exc:
                return f"WRITE-FAILED file={path}/topic.txt: {exc}"
            except ValueError:
                return "ERROR: unsafe research topic path"
            return f"Created project: {path}\nFolders: src/ data/ runs/ figures/"
    except (OSError, ValueError) as exc:
        return f"ERROR: could not create research project directories for {project}: {exc}"


def read_research_instructions(memory_dir, workflow_dir, project, filename):
    try:
        if not validate_file_or_folder_name(filename):
            raise ValueError("invalid filename")
        with _research_project(memory_dir, workflow_dir, project) as (path, fd):
            with _research_target(path, fd, filename) as (_, parent_fd, name):
                with _regular_file(parent_fd, name, os.O_RDONLY) as stream:
                    return ["ok", stream.read().decode("utf-8")]
    except FileNotFoundError:
        return ["error", f"ERROR: file not found: {project}/{filename}"]
    except UnicodeDecodeError:
        return ["error", f"ERROR: instructions must be UTF-8: {project}/{filename}"]
    except ValueError:
        return ["error", f"ERROR: path traversal rejected for {project}/{filename}"]
    except OSError as exc:
        return ["error", f"ERROR: could not read {project}/{filename}: {exc}"]


def _snippet(raw):
    # escape backslashes first so literal \n in content stays distinguishable
    # from a real newline in the rendered snippet
    text = raw.decode("utf-8", errors="replace")
    return text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _readback(stream):
    size = os.fstat(stream.fileno()).st_size
    head = stream.read(SNIPPET_BYTES)
    tail = b""
    if size > 2 * SNIPPET_BYTES:
        stream.seek(-SNIPPET_BYTES, os.SEEK_END)
        tail = stream.read(SNIPPET_BYTES)
    digest = "skipped(large)"
    if size <= HASH_MAX_BYTES:
        stream.seek(0)
        digest = hashlib.sha256(stream.read()).hexdigest()[:16]
    return size, digest, head, tail


def _verified_result(word, path, readback):
    size, digest, head, tail = readback
    logger.info(f"[FILE_IO] {word.lower()} ok file={path} bytes={size} sha256={digest}")
    return (f"{word}-VERIFIED file={path} bytes={size} sha256={digest} "
            f"head='{_snippet(head)}' tail='{_snippet(tail)}'")


def _line_separator(path):
    """Newline needed to start a new line at the end of path, empty when
    the file is empty or already ends with one. Read as bytes so a
    multi-byte character at the end is not decoded from its middle."""
    try:
        if os.path.getsize(path) == 0:
            return b""
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return b"" if f.read(1) == b"\n" else b"\n"
    except OSError:
        return b""


def _write(path, data, append):
    path = str(path)
    word = "APPEND" if append else "WRITE"
    if append:
        data = _line_separator(path) + data + b"\n"
    try:
        with open(path, "ab" if append else "wb") as f:
            f.write(data)
        with open(path, "rb") as stream:
            return _verified_result(word, path, _readback(stream))
    except Exception as e:  # the skill must return a result, never raise into the loop
        logger.error(f"[FILE_IO] {word.lower()} failed file={path} err={e}")
        return f"{word}-FAILED file={path}: {e}"


def write_file(path, content):
    return _write(path, str(content).encode("utf-8"), append=False)


def append_file(path, content):
    path = str(path)
    if not os.path.exists(path):
        logger.error(f"[FILE_IO] append failed file={path} err=file does not exist")
        return f"APPEND-FAILED file={path}: file does not exist"
    return _write(path, str(content).encode("utf-8"), append=True)


def write_file_b64(path, content_b64):
    try:
        # tolerate MIME-style line-wrapped base64 (embedded whitespace)
        data = base64.b64decode(re.sub(r"\s+", "", str(content_b64)), validate=True)
    except Exception as e:
        logger.error(f"[FILE_IO] write failed file={path} err=invalid base64")
        return f"WRITE-FAILED file={path}: invalid base64 ({e})"
    return _write(path, data, append=False)


def delete_file(path):
    path = str(path)
    if not os.path.lexists(path):
        logger.error(f"[FILE_IO] delete failed file={path} err=file does not exist")
        return f"DELETE-FAILED file={path}: file does not exist"
    if os.path.isdir(path):
        logger.error(f"[FILE_IO] delete failed file={path} err=path is a directory")
        return f"DELETE-FAILED file={path}: path is a directory"
    try:
        os.remove(path)
    except Exception as e:  # the skill must return a result, never raise into the loop
        logger.error(f"[FILE_IO] delete failed file={path} err={e}")
        return f"DELETE-FAILED file={path}: {e}"
    if os.path.exists(path):  # race: something recreated it between remove() and here
        logger.error(f"[FILE_IO] delete verification failed file={path} still exists after remove")
        return f"DELETE-FAILED file={path}: file still exists after removal"
    logger.info(f"[FILE_IO] delete ok file={path}")
    return f"DELETE-VERIFIED file={path}"
