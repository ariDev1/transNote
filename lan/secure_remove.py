#!/usr/bin/python3
# Race-resistant recursive removal for one TransNote attachment directory.

import errno
import os
import re
import stat
import sys

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", re.ASCII)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | O_CLOEXEC


class SafetyError(RuntimeError):
    pass


def _validate_directory(fd, expected_uid, expected_dev):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise SafetyError("not a directory")
    if info.st_uid != expected_uid:
        raise SafetyError("unexpected owner")
    if info.st_dev != expected_dev:
        raise SafetyError("cross-device directory")
    return info


def _same_open_directory(parent_fd, name, opened_info):
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    return (
        stat.S_ISDIR(current.st_mode)
        and current.st_dev == opened_info.st_dev
        and current.st_ino == opened_info.st_ino
    )


def _remove_directory_contents(dir_fd, expected_uid, expected_dev):
    # Names come from the already-open directory. Every lookup below is
    # relative to this retained descriptor. Checked parents are never
    # reopened by pathname, and symlinks are never traversed.
    for name in os.listdir(dir_fd):
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue

        if stat.S_ISDIR(info.st_mode):
            try:
                child_fd = os.open(name, DIR_FLAGS, dir_fd=dir_fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                # A directory changed to a symlink/non-directory between
                # inspection and open. Fail closed instead of following it.
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise SafetyError("directory changed during traversal") from exc
                raise

            try:
                child_info = _validate_directory(
                    child_fd, expected_uid, expected_dev
                )
                _remove_directory_contents(
                    child_fd, expected_uid, expected_dev
                )
                if not _same_open_directory(dir_fd, name, child_info):
                    raise SafetyError("directory changed before removal")
                os.rmdir(name, dir_fd=dir_fd)
            finally:
                os.close(child_fd)
        else:
            # unlink() removes a symlink itself and does not follow it.
            try:
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                continue


def secure_remove(root_path, note_id):
    if not SAFE_ID_RE.fullmatch(note_id or ""):
        return 2

    try:
        root_fd = os.open(root_path, DIR_FLAGS)
    except FileNotFoundError:
        return 0
    except OSError:
        return 3

    try:
        root_info = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != os.geteuid()
        ):
            return 3

        try:
            note_fd = os.open(note_id, DIR_FLAGS, dir_fd=root_fd)
        except FileNotFoundError:
            return 0
        except OSError:
            return 3

        try:
            note_info = _validate_directory(
                note_fd, root_info.st_uid, root_info.st_dev
            )
            _remove_directory_contents(
                note_fd, root_info.st_uid, root_info.st_dev
            )
            if not _same_open_directory(root_fd, note_id, note_info):
                return 3
            os.rmdir(note_id, dir_fd=root_fd)
            return 0
        except (OSError, SafetyError):
            return 3
        finally:
            os.close(note_fd)
    finally:
        os.close(root_fd)


def main(argv):
    if len(argv) != 3:
        return 2
    return secure_remove(argv[1], argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
