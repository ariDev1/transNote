#!/usr/bin/python3
# Race-resistant recursive removal for one TransNote attachment directory.

import errno
import hashlib
import os
import re
import stat
import sys

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", re.ASCII)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | O_CLOEXEC


class SafetyError(RuntimeError):
    pass


def _open_directory_path(path):
    """Open every directory component without following symlinks."""
    raw = os.fspath(path)
    if raw == "":
        raise FileNotFoundError(raw)

    start = os.sep if os.path.isabs(raw) else "."
    parts = [
        part
        for part in raw.split(os.sep)
        if part not in ("", ".")
    ]

    fd = os.open(start, DIR_FLAGS)
    try:
        for part in parts:
            next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


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
        root_fd = _open_directory_path(root_path)
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


def _open_or_create_directory_path(path):
    """Open a directory path without following any symlink component."""
    raw = os.fspath(path)
    if raw == "":
        raise FileNotFoundError(raw)

    start = os.sep if os.path.isabs(raw) else "."
    parts = [
        part
        for part in raw.split(os.sep)
        if part not in ("", ".")
    ]

    fd = os.open(start, DIR_FLAGS)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)

            os.close(fd)
            fd = next_fd

        return fd
    except BaseException:
        os.close(fd)
        raise


def secure_peer_read(
    root_path,
    max_file_bytes_raw,
    max_aggregate_bytes_raw,
    names,
):
    try:
        max_file_bytes = int(max_file_bytes_raw)
        max_aggregate_bytes = int(max_aggregate_bytes_raw)
    except (TypeError, ValueError):
        return 2

    if max_file_bytes < 0 or max_aggregate_bytes < 0:
        return 2

    try:
        root_fd = _open_directory_path(root_path)
    except OSError:
        for index, _name in enumerate(names):
            print(f"===TRANSNOTEPEER:{index}===")
            print("REJECTED:READFAIL")
        return 0

    total = 0
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | O_CLOEXEC

    try:
        for index, name in enumerate(names):
            print(f"===TRANSNOTEPEER:{index}===")

            if (
                not name
                or name in (".", "..")
                or "/" in name
                or "\\" in name
                or "\0" in name
                or not name.endswith(".json")
            ):
                print("REJECTED:READFAIL")
                continue

            try:
                file_fd = os.open(
                    name,
                    file_flags,
                    dir_fd=root_fd,
                )
            except OSError:
                print("REJECTED:READFAIL")
                continue

            try:
                before = os.fstat(file_fd)

                if not stat.S_ISREG(before.st_mode):
                    print("REJECTED:READFAIL")
                    continue

                size = before.st_size

                if size < 0:
                    print("REJECTED:READFAIL")
                    continue

                if size > max_file_bytes:
                    print("REJECTED:FILE_BYTES")
                    continue

                if total + size > max_aggregate_bytes:
                    print("REJECTED:AGGREGATE_BYTES")
                    continue

                total += size

                chunks = []
                remaining = size

                while remaining > 0:
                    chunk = os.read(
                        file_fd,
                        min(1024 * 1024, remaining),
                    )
                    if not chunk:
                        break

                    chunks.append(chunk)
                    remaining -= len(chunk)

                after = os.fstat(file_fd)

                if (
                    remaining != 0
                    or before.st_dev != after.st_dev
                    or before.st_ino != after.st_ino
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns
                ):
                    print("REJECTED:READFAIL")
                    continue

                payload = b"".join(chunks)

                try:
                    decoded = payload.decode("utf-8")
                except UnicodeDecodeError:
                    print("REJECTED:READFAIL")
                    continue

                sys.stdout.write(decoded)
                if not decoded.endswith("\n"):
                    sys.stdout.write("\n")
            finally:
                os.close(file_fd)

        return 0
    finally:
        os.close(root_fd)


def _trusted_file_matches(
    note_fd,
    file_name,
    expected_size,
    expected_sha,
    owner_uid,
    device,
):
    flags = os.O_RDONLY | os.O_NOFOLLOW | O_CLOEXEC

    try:
        file_fd = os.open(
            file_name,
            flags,
            dir_fd=note_fd,
        )
    except OSError:
        return False

    try:
        before = os.fstat(file_fd)

        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != owner_uid
            or before.st_dev != device
            or before.st_size != expected_size
        ):
            return False

        digest = hashlib.sha256()
        total = 0

        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break

            total += len(chunk)
            if total > expected_size:
                return False

            digest.update(chunk)

        after = os.fstat(file_fd)

        if (
            total != expected_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            return False

        return digest.hexdigest() == expected_sha.lower()
    finally:
        os.close(file_fd)


def secure_verify_copy(
    source_root,
    note_id,
    file_name,
    declared_size_raw,
    max_size_raw,
    expected_sha,
    trusted_root,
):
    if not SAFE_ID_RE.fullmatch(note_id or ""):
        return 2
    if (
        not file_name
        or file_name in (".", "..")
        or "/" in file_name
        or "\\" in file_name
        or "\0" in file_name
    ):
        return 2
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha or ""):
        return 2

    try:
        declared_size = int(declared_size_raw)
        max_size = int(max_size_raw)
    except (TypeError, ValueError):
        return 2

    memory_limit = 25 * 1024 * 1024

    if (
        declared_size < 0
        or max_size < 0
        or declared_size > max_size
        or declared_size > memory_limit
    ):
        print("BAD_SIZE")
        return 0

    try:
        source_root_fd = _open_directory_path(source_root)
    except FileNotFoundError:
        print("MISSING")
        return 0
    except OSError:
        return 3

    try:
        source_root_info = os.fstat(source_root_fd)
        if (
            not stat.S_ISDIR(source_root_info.st_mode)
            or source_root_info.st_uid != os.geteuid()
        ):
            return 3

        try:
            source_note_fd = os.open(
                note_id,
                DIR_FLAGS,
                dir_fd=source_root_fd,
            )
        except FileNotFoundError:
            print("MISSING")
            return 0
        except OSError:
            return 3

        try:
            _validate_directory(
                source_note_fd,
                source_root_info.st_uid,
                source_root_info.st_dev,
            )

            source_flags = os.O_RDONLY | os.O_NOFOLLOW | O_CLOEXEC

            try:
                source_fd = os.open(
                    file_name,
                    source_flags,
                    dir_fd=source_note_fd,
                )
            except FileNotFoundError:
                print("MISSING")
                return 0
            except OSError:
                return 3

            try:
                before = os.fstat(source_fd)

                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != source_root_info.st_uid
                    or before.st_dev != source_root_info.st_dev
                ):
                    return 3

                if (
                    before.st_size != declared_size
                    or before.st_size > max_size
                    or before.st_size > memory_limit
                ):
                    print("BAD_SIZE")
                    return 0

                # Read into bounded memory first. No trusted-cache payload is
                # created until size and SHA-256 are proven valid.
                chunks = []
                digest = hashlib.sha256()
                total = 0

                while True:
                    chunk = os.read(source_fd, 1024 * 1024)
                    if not chunk:
                        break

                    total += len(chunk)

                    if (
                        total > declared_size
                        or total > max_size
                        or total > memory_limit
                    ):
                        print("BAD_SIZE")
                        return 0

                    digest.update(chunk)
                    chunks.append(chunk)

                after = os.fstat(source_fd)

                if (
                    total != declared_size
                    or before.st_dev != after.st_dev
                    or before.st_ino != after.st_ino
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns
                ):
                    print("BAD_SIZE")
                    return 0

                if digest.hexdigest() != expected_sha.lower():
                    print("BAD_HASH")
                    return 0

                payload = b"".join(chunks)

                try:
                    trusted_root_fd = _open_or_create_directory_path(
                        trusted_root
                    )
                except OSError:
                    return 3

                try:
                    trusted_root_info = os.fstat(trusted_root_fd)

                    if (
                        not stat.S_ISDIR(trusted_root_info.st_mode)
                        or trusted_root_info.st_uid != os.geteuid()
                    ):
                        return 3

                    try:
                        trusted_note_fd = os.open(
                            note_id,
                            DIR_FLAGS,
                            dir_fd=trusted_root_fd,
                        )
                    except FileNotFoundError:
                        try:
                            os.mkdir(
                                note_id,
                                0o700,
                                dir_fd=trusted_root_fd,
                            )
                        except FileExistsError:
                            pass

                        try:
                            trusted_note_fd = os.open(
                                note_id,
                                DIR_FLAGS,
                                dir_fd=trusted_root_fd,
                            )
                        except OSError:
                            return 3
                    except OSError:
                        return 3

                    try:
                        _validate_directory(
                            trusted_note_fd,
                            trusted_root_info.st_uid,
                            trusted_root_info.st_dev,
                        )

                        # Do not rewrite an unchanged trusted copy.
                        if _trusted_file_matches(
                            trusted_note_fd,
                            file_name,
                            declared_size,
                            expected_sha,
                            trusted_root_info.st_uid,
                            trusted_root_info.st_dev,
                        ):
                            print("VERIFIED")
                            return 0

                        temp_name = (
                            ".transnote-verify-"
                            + str(os.getpid())
                            + "-"
                            + os.urandom(8).hex()
                        )
                        temp_fd = -1

                        try:
                            temp_fd = os.open(
                                temp_name,
                                os.O_WRONLY
                                | os.O_CREAT
                                | os.O_EXCL
                                | os.O_NOFOLLOW
                                | O_CLOEXEC,
                                0o600,
                                dir_fd=trusted_note_fd,
                            )

                            view = memoryview(payload)

                            while view:
                                written = os.write(temp_fd, view)
                                if written <= 0:
                                    return 3
                                view = view[written:]

                            os.fchmod(temp_fd, 0o600)
                            os.close(temp_fd)
                            temp_fd = -1

                            os.replace(
                                temp_name,
                                file_name,
                                src_dir_fd=trusted_note_fd,
                                dst_dir_fd=trusted_note_fd,
                            )

                            print("VERIFIED")
                            return 0
                        except OSError:
                            return 3
                        finally:
                            if temp_fd >= 0:
                                os.close(temp_fd)

                            try:
                                os.unlink(
                                    temp_name,
                                    dir_fd=trusted_note_fd,
                                )
                            except FileNotFoundError:
                                pass
                    finally:
                        os.close(trusted_note_fd)
                finally:
                    os.close(trusted_root_fd)
            finally:
                os.close(source_fd)
        except (OSError, SafetyError):
            return 3
        finally:
            os.close(source_note_fd)
    finally:
        os.close(source_root_fd)


def secure_copy(source_path, root_path, note_id, file_name):
    if not SAFE_ID_RE.fullmatch(note_id or ""):
        return 2
    if (
        not file_name
        or file_name in (".", "..")
        or "/" in file_name
        or "\\" in file_name
        or "\0" in file_name
    ):
        return 2

    source_flags = os.O_RDONLY | os.O_NOFOLLOW | O_CLOEXEC
    try:
        source_fd = os.open(source_path, source_flags)
    except OSError:
        return 3

    try:
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode):
            return 3

        try:
            root_fd = _open_or_create_directory_path(root_path)
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
                try:
                    os.mkdir(note_id, 0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass
                try:
                    note_fd = os.open(note_id, DIR_FLAGS, dir_fd=root_fd)
                except OSError:
                    return 3
            except OSError:
                return 3

            try:
                _validate_directory(
                    note_fd,
                    root_info.st_uid,
                    root_info.st_dev,
                )

                dest_fd = -1
                try:
                    try:
                        dest_fd = os.open(
                            file_name,
                            source_flags,
                            dir_fd=note_fd,
                        )
                    except FileNotFoundError:
                        pass
                    except OSError:
                        return 3

                    if dest_fd >= 0:
                        dest_info = os.fstat(dest_fd)
                        if (
                            not stat.S_ISREG(dest_info.st_mode)
                            or dest_info.st_uid != root_info.st_uid
                            or dest_info.st_dev != root_info.st_dev
                        ):
                            return 3

                        identical = True
                        while True:
                            source_chunk = os.read(source_fd, 1024 * 1024)
                            dest_chunk = os.read(dest_fd, 1024 * 1024)

                            if source_chunk != dest_chunk:
                                identical = False
                                break
                            if not source_chunk:
                                break

                        if identical:
                            return 0

                        os.lseek(source_fd, 0, os.SEEK_SET)
                finally:
                    if dest_fd >= 0:
                        os.close(dest_fd)

                temp_name = (
                    ".transnote-copy-"
                    + str(os.getpid())
                    + "-"
                    + os.urandom(8).hex()
                )
                temp_fd = -1

                try:
                    temp_fd = os.open(
                        temp_name,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | os.O_NOFOLLOW
                        | O_CLOEXEC,
                        0o600,
                        dir_fd=note_fd,
                    )

                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break

                        view = memoryview(chunk)
                        while view:
                            written = os.write(temp_fd, view)
                            view = view[written:]

                    os.fchmod(temp_fd, 0o600)
                    os.close(temp_fd)
                    temp_fd = -1

                    os.replace(
                        temp_name,
                        file_name,
                        src_dir_fd=note_fd,
                        dst_dir_fd=note_fd,
                    )
                    return 0
                except OSError:
                    return 3
                finally:
                    if temp_fd >= 0:
                        os.close(temp_fd)
                    try:
                        os.unlink(temp_name, dir_fd=note_fd)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(note_fd)
        finally:
            os.close(root_fd)
    finally:
        os.close(source_fd)


def secure_unlink(root_path, note_id, file_name):
    if not SAFE_ID_RE.fullmatch(note_id or ""):
        return 2
    if (
        not file_name
        or file_name in (".", "..")
        or "/" in file_name
        or "\\" in file_name
        or "\0" in file_name
    ):
        return 2

    try:
        root_fd = _open_directory_path(root_path)
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
            _validate_directory(
                note_fd,
                root_info.st_uid,
                root_info.st_dev,
            )
            try:
                os.unlink(file_name, dir_fd=note_fd)
            except FileNotFoundError:
                return 0
            except IsADirectoryError:
                return 3
            return 0
        except (OSError, SafetyError):
            return 3
        finally:
            os.close(note_fd)
    finally:
        os.close(root_fd)



def secure_prune_verified(trusted_root, entries):
    keep = {}

    if entries:
        # Runtime form:
        #   note-id file-name declared-size sha256
        if len(entries) % 4 != 0:
            return 2

        for index in range(0, len(entries), 4):
            note_id = entries[index]
            file_name = entries[index + 1]
            size_raw = entries[index + 2]
            expected_sha = entries[index + 3]

            if not SAFE_ID_RE.fullmatch(note_id or ""):
                return 2
            if (
                not file_name
                or file_name in (".", "..")
                or "/" in file_name
                or "\\" in file_name
                or "\0" in file_name
            ):
                return 2
            if not re.fullmatch(
                r"[0-9a-fA-F]{64}",
                expected_sha or "",
            ):
                return 2

            try:
                expected_size = int(size_raw)
            except (TypeError, ValueError):
                return 2

            if (
                expected_size < 0
                or expected_size > 25 * 1024 * 1024
            ):
                return 2

            keep.setdefault(note_id, {})[file_name] = (
                expected_size,
                expected_sha.lower(),
            )

    try:
        root_fd = _open_directory_path(trusted_root)
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

        for note_id in sorted(os.listdir(root_fd)):
            if not SAFE_ID_RE.fullmatch(note_id or ""):
                continue

            try:
                note_fd = os.open(
                    note_id,
                    DIR_FLAGS,
                    dir_fd=root_fd,
                )
            except OSError:
                return 3

            empty_after = False

            try:
                _validate_directory(
                    note_fd,
                    root_info.st_uid,
                    root_info.st_dev,
                )

                allowed = keep.get(note_id, {})

                for file_name in sorted(os.listdir(note_fd)):
                    metadata = allowed.get(file_name)
                    keep_file = file_name in allowed

                    if keep_file and metadata is not None:
                        expected_size, expected_sha = metadata

                        keep_file = _trusted_file_matches(
                            note_fd,
                            file_name,
                            expected_size,
                            expected_sha,
                            root_info.st_uid,
                            root_info.st_dev,
                        )

                    if keep_file:
                        continue

                    try:
                        os.unlink(
                            file_name,
                            dir_fd=note_fd,
                        )
                    except FileNotFoundError:
                        pass
                    except OSError:
                        return 3

                empty_after = len(os.listdir(note_fd)) == 0
            except (OSError, SafetyError):
                return 3
            finally:
                os.close(note_fd)

            if empty_after:
                try:
                    os.rmdir(
                        note_id,
                        dir_fd=root_fd,
                    )
                except FileNotFoundError:
                    pass
                except OSError:
                    return 3

        return 0
    finally:
        os.close(root_fd)


def main(argv):
    if len(argv) == 3:
        return secure_remove(argv[1], argv[2])
    if len(argv) == 5 and argv[1] == "unlink":
        return secure_unlink(argv[2], argv[3], argv[4])
    if len(argv) == 6 and argv[1] == "copy":
        return secure_copy(
            argv[2],
            argv[3],
            argv[4],
            argv[5],
        )
    if len(argv) >= 3 and argv[1] == "prune-verified":
        return secure_prune_verified(
            argv[2],
            argv[3:],
        )
    if len(argv) == 9 and argv[1] == "verify-copy":
        return secure_verify_copy(
            argv[2],
            argv[3],
            argv[4],
            argv[5],
            argv[6],
            argv[7],
            argv[8],
        )
    if len(argv) >= 6 and argv[1] == "peer-read":
        return secure_peer_read(
            argv[2],
            argv[3],
            argv[4],
            argv[5:],
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
