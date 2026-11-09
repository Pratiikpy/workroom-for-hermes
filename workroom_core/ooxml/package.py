"""Safe reading and byte-preserving rewriting of Office (OPC) zip packages.

Untouched entries are copied as their original local header plus compressed bytes, and their central
directory fields are kept, so a package rewritten with no edits is byte-identical to the input. Edited
entries are recompressed. ZIP64, encryption and multi-disk archives are refused, not guessed at.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from collections.abc import Iterable, Mapping

_SIG_LOCAL = 0x04034B50
_SIG_CENTRAL = 0x02014B50
_SIG_EOCD = 0x06054B50
_SIG_DESCRIPTOR = 0x08074B50
_LOCAL = struct.Struct("<IHHHHHIIIHH")
_CENTRAL = struct.Struct("<IHHHHHHIIIHHHHHII")
_EOCD = struct.Struct("<IHHHHIIH")

MAX_ENTRIES = 20000
MAX_TOTAL_UNCOMPRESSED = 2 * 1024**3
MAX_ENTRY_UNCOMPRESSED = 512 * 1024**2
MAX_RATIO = 1000


class PackageError(ValueError):
    """The file is not a safe, supported Office package."""


@dataclass(frozen=True)
class Entry:
    name: str
    flags: int
    method: int
    dos_time: int
    dos_date: int
    crc: int
    comp_size: int
    size: int
    extra_central: bytes
    comment: bytes
    version_made: int
    version_needed: int
    internal_attr: int
    external_attr: int
    raw: bytes  # original local header + compressed data (+ data descriptor), copied verbatim


@dataclass
class Package:
    entries: list[Entry] = field(default_factory=list)
    by_name: dict[str, Entry] = field(default_factory=dict)
    trailing_comment: bytes = b""
    tail: bytes = b""  # any bytes after the end-of-central-directory record, kept as found

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def read(self, name: str) -> bytes:
        entry = self.by_name[name]
        return _decompress(entry)


def _validate_name(name: str) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise PackageError(f"unsafe entry name: {name!r}")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or (len(name) > 1 and name[1] == ":"):
        raise PackageError(f"unsafe entry name: {name!r}")


def _decompress(entry: Entry) -> bytes:
    lh = _LOCAL.unpack_from(entry.raw, 0)
    name_len, extra_len = lh[9], lh[10]
    start = _LOCAL.size + name_len + extra_len
    data = entry.raw[start : start + entry.comp_size]
    if entry.method == 0:
        out = data
    elif entry.method == 8:
        d = zlib.decompressobj(-15)
        try:
            out = d.decompress(data, entry.size + 1)
        except zlib.error as exc:
            raise PackageError(f"entry {entry.name!r} has corrupt compressed data: {exc}") from exc
        if d.unconsumed_tail or len(out) > entry.size:
            raise PackageError(f"entry {entry.name!r} is larger than declared")
    else:
        raise PackageError(f"unsupported compression method {entry.method} in {entry.name!r}")
    if len(out) != entry.size or (zlib.crc32(out) & 0xFFFFFFFF) != entry.crc:
        raise PackageError(f"entry {entry.name!r} failed its size or CRC check")
    return out


def open_package(data: bytes) -> Package:
    """Parse a package from bytes with safety limits. Raises PackageError on anything unsafe or unsupported."""
    eocd_at = data.rfind(struct.pack("<I", _SIG_EOCD))
    if eocd_at < 0 or len(data) - eocd_at < _EOCD.size:
        raise PackageError("not a zip package (no end-of-central-directory record)")
    (_, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len) = _EOCD.unpack_from(data, eocd_at)
    if disk or cd_disk or n_disk != n_total:
        raise PackageError("multi-disk archives are not supported")
    if n_total == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        raise PackageError("ZIP64 packages are not supported")
    if n_total > MAX_ENTRIES:
        raise PackageError("too many entries")
    comment_end = eocd_at + _EOCD.size + comment_len
    pkg = Package(trailing_comment=data[eocd_at + _EOCD.size : comment_end], tail=data[comment_end:])
    pos = cd_offset
    total = 0
    local_offsets: list[int] = []
    central: list[tuple] = []
    for _ in range(n_total):
        if pos + _CENTRAL.size > len(data):
            raise PackageError("truncated central directory")
        f = _CENTRAL.unpack_from(data, pos)
        if f[0] != _SIG_CENTRAL:
            raise PackageError("bad central directory signature")
        (_, vmade, vneed, flags, method, dtime, ddate, crc, csize, usize, nlen, elen, clen, dnum, iattr, eattr, loff) = f
        if flags & 0x1 or flags & 0x40:
            raise PackageError("encrypted entries are not supported")
        if csize == 0xFFFFFFFF or usize == 0xFFFFFFFF or loff == 0xFFFFFFFF or dnum:
            raise PackageError("ZIP64 or multi-disk entries are not supported")
        name_b = data[pos + _CENTRAL.size : pos + _CENTRAL.size + nlen]
        try:
            name = name_b.decode("utf-8" if flags & 0x800 else "cp437")
        except UnicodeDecodeError as exc:
            raise PackageError("undecodable entry name") from exc
        _validate_name(name)
        extra = data[pos + _CENTRAL.size + nlen : pos + _CENTRAL.size + nlen + elen]
        comment = data[pos + _CENTRAL.size + nlen + elen : pos + _CENTRAL.size + nlen + elen + clen]
        if usize > MAX_ENTRY_UNCOMPRESSED:
            raise PackageError(f"entry {name!r} is too large")
        if csize and usize / max(csize, 1) > MAX_RATIO and usize > 1024 * 1024:
            raise PackageError(f"entry {name!r} has a suspicious compression ratio")
        total += usize
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise PackageError("package is too large when uncompressed")
        central.append((name, flags, method, dtime, ddate, crc, csize, usize, extra, comment, vmade, vneed, iattr, eattr, loff))
        local_offsets.append(loff)
        pos += _CENTRAL.size + nlen + elen + clen
    if len({c[0] for c in central}) != len(central):
        raise PackageError("duplicate entry names")
    for (name, flags, method, dtime, ddate, crc, csize, usize, extra, comment, vmade, vneed, iattr, eattr, loff) in central:
        if loff + _LOCAL.size > len(data):
            raise PackageError("local header offset out of range")
        lh = _LOCAL.unpack_from(data, loff)
        if lh[0] != _SIG_LOCAL:
            raise PackageError("bad local header signature")
        end = loff + _LOCAL.size + lh[9] + lh[10] + csize
        if flags & 0x8:
            if data[end : end + 4] == struct.pack("<I", _SIG_DESCRIPTOR):
                end += 16
            else:
                end += 12
        if end > len(data):
            raise PackageError("entry data out of range")
        entry = Entry(name, flags, method, dtime, ddate, crc, csize, usize, extra, comment, vmade, vneed, iattr, eattr, data[loff:end])
        pkg.entries.append(entry)
        pkg.by_name[name] = entry
    return pkg


def _make_entry(template: Entry | None, name: str, payload: bytes) -> Entry:
    """Build a freshly compressed entry, reusing the template's timestamps and attributes when present."""
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(payload) + comp.flush()
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    flags = 0x800 if not name.isascii() else 0
    dtime = template.dos_time if template else 0
    ddate = template.dos_date if template else 0x21
    name_b = name.encode("utf-8")
    local = _LOCAL.pack(_SIG_LOCAL, 20, flags, 8, dtime, ddate, crc, len(body), len(payload), len(name_b), 0)
    return Entry(
        name, flags, 8, dtime, ddate, crc, len(body), len(payload),
        b"", b"", template.version_made if template else 20, 20, template.internal_attr if template else 0,
        template.external_attr if template else 0, local + name_b + body,
    )


def rewrite(pkg: Package, replacements: Mapping[str, bytes], additions: Mapping[str, bytes] | None = None) -> bytes:
    """Write a package: untouched entries verbatim, replaced entries recompressed, additions appended."""
    for name in list(replacements) + list(additions or {}):
        _validate_name(name)
    missing = [n for n in replacements if n not in pkg.by_name]
    if missing:
        raise PackageError(f"cannot replace missing entries: {missing}")
    clash = [n for n in (additions or {}) if n in pkg.by_name]
    if clash:
        raise PackageError(f"cannot add existing entries: {clash}")
    out = bytearray()
    central = bytearray()
    count = 0

    def emit(e: Entry) -> None:
        nonlocal count
        offset = len(out)
        out.extend(e.raw)
        name_b = e.name.encode("utf-8" if e.flags & 0x800 else "cp437")
        central.extend(
            _CENTRAL.pack(_SIG_CENTRAL, e.version_made, e.version_needed, e.flags, e.method, e.dos_time, e.dos_date,
                          e.crc, e.comp_size, e.size, len(name_b), len(e.extra_central), len(e.comment), 0,
                          e.internal_attr, e.external_attr, offset)
        )
        central.extend(name_b)
        central.extend(e.extra_central)
        central.extend(e.comment)
        count += 1

    for e in pkg.entries:
        emit(_make_entry(e, e.name, replacements[e.name]) if e.name in replacements else e)
    for name, payload in (additions or {}).items():
        emit(_make_entry(None, name, payload))
    cd_offset = len(out)
    out.extend(central)
    out.extend(_EOCD.pack(_SIG_EOCD, 0, 0, count, count, len(central), cd_offset, len(pkg.trailing_comment)))
    out.extend(pkg.trailing_comment)
    out.extend(pkg.tail)
    return bytes(out)


@dataclass(frozen=True)
class PartReport:
    unchanged: tuple[str, ...]
    changed: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]


def compare(before: Package, after: Package) -> PartReport:
    """Part-level change report. An entry is unchanged only when its decompressed content hash is equal."""
    unchanged, changed = [], []
    for name, e in before.by_name.items():
        if name in after.by_name:
            same = (e.crc, e.size) == (after.by_name[name].crc, after.by_name[name].size) and _decompress(e) == after.read(name)
            (unchanged if same else changed).append(name)
    added = tuple(n for n in after.by_name if n not in before.by_name)
    removed = tuple(n for n in before.by_name if n not in after.by_name)
    return PartReport(tuple(unchanged), tuple(changed), added, removed)


def raw_unchanged(before: Package, after: Package, names: Iterable[str]) -> list[str]:
    """Names whose compressed bytes (not just decompressed content) are identical in both packages."""
    return [n for n in names if n in after.by_name and _payload(before.by_name[n]) == _payload(after.by_name[n])]


def _payload(e: Entry) -> bytes:
    lh = _LOCAL.unpack_from(e.raw, 0)
    start = _LOCAL.size + lh[9] + lh[10]
    return e.raw[start : start + e.comp_size]
