"""Minimal read-only Compound File Binary (OLE2) reader.

레거시 Office(DOC/XLS/PPT), Outlook MSG, HWP 5, 암호화된 OOXML, OLE 내장 개체가 이 형식이다.
디렉터리 목록과 스트림 읽기만 지원한다. 손상·악의적 파일에 대비해 모든 체인 길이를 제한한다.
"""
import struct

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END, _FREE = 0xFFFFFFFE, 0xFFFFFFFF
_NOSTREAM = 0xFFFFFFFF


class CfbError(Exception):
    pass


class Entry:
    __slots__ = ("sid", "name", "kind", "left", "right", "child", "start", "size", "path")

    def __init__(self, sid, name, kind, left, right, child, start, size):
        self.sid, self.name, self.kind = sid, name, kind
        self.left, self.right, self.child, self.start, self.size = left, right, child, start, size
        self.path = ""

    @property
    def is_storage(self) -> bool:
        return self.kind in (1, 5)


class CompoundFile:
    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != SIGNATURE:
            raise CfbError("CFB 서명이 아닙니다.")
        self.data = data
        shift = struct.unpack_from("<H", data, 0x1E)[0]
        mini_shift = struct.unpack_from("<H", data, 0x20)[0]
        if shift not in (9, 12) or mini_shift != 6:
            raise CfbError("지원하지 않는 섹터 크기입니다.")
        self.sector = 1 << shift
        self.mini_sector = 1 << mini_shift
        n_fat, first_dir = struct.unpack_from("<II", data, 0x2C)
        self.cutoff, first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIIII", data, 0x38)
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        sector_id, guard = first_difat, 0
        while sector_id not in (_END, _FREE) and guard < max(n_difat, 1) + 4:
            body = self._sector(sector_id)
            values = struct.unpack_from(f"<{self.sector // 4}I", body)
            difat.extend(values[:-1])
            sector_id, guard = values[-1], guard + 1
        fat_sectors = [s for s in difat if s not in (_END, _FREE)][: max(n_fat, 0) or None]
        self.fat = []
        for s in fat_sectors:
            self.fat.extend(struct.unpack_from(f"<{self.sector // 4}I", self._sector(s)))
        directory = self._chain_bytes(first_dir, self.fat, self.sector, self._sector)
        self.entries: list[Entry] = []
        for i in range(len(directory) // 128):
            raw = directory[i * 128:(i + 1) * 128]
            name_len = struct.unpack_from("<H", raw, 0x40)[0]
            name = raw[: max(0, min(name_len, 64) - 2)].decode("utf-16-le", "replace")
            kind = raw[0x42]
            left, right, child = struct.unpack_from("<III", raw, 0x44)
            start = struct.unpack_from("<I", raw, 0x74)[0]
            size = struct.unpack_from("<Q", raw, 0x78)[0]
            if self.sector == 512:
                size &= 0xFFFFFFFF
            self.entries.append(Entry(i, name, kind, left, right, child, start, size))
        if not self.entries or self.entries[0].kind != 5:
            raise CfbError("루트 항목이 없습니다.")
        root = self.entries[0]
        self.minifat = []
        if n_minifat and first_minifat not in (_END, _FREE):
            raw = self._chain_bytes(first_minifat, self.fat, self.sector, self._sector)
            self.minifat = list(struct.unpack_from(f"<{len(raw) // 4}I", raw))
        self.ministream = self._chain_bytes(root.start, self.fat, self.sector, self._sector, limit=root.size) if root.start not in (_END, _FREE) else b""
        self._assign_paths()

    def _sector(self, sid: int) -> bytes:
        offset = (sid + 1) * self.sector
        if offset + self.sector > len(self.data) + self.sector:  # allow short final sector
            raise CfbError("섹터가 파일 범위를 벗어났습니다.")
        return self.data[offset: offset + self.sector].ljust(self.sector, b"\0")

    def _chain_bytes(self, start, table, size, reader, limit=None) -> bytes:
        out, sid, seen = [], start, 0
        cap = len(table) + 1
        while sid not in (_END, _FREE) and sid < len(table) and seen < cap:
            out.append(reader(sid))
            seen += 1
            if limit is not None and seen * size >= limit:
                break
            sid = table[sid]
        data = b"".join(out)
        return data[:limit] if limit is not None else data

    def _mini(self, sid: int) -> bytes:
        offset = sid * self.mini_sector
        return self.ministream[offset: offset + self.mini_sector].ljust(self.mini_sector, b"\0")

    def _assign_paths(self) -> None:
        seen: set[int] = set()

        def walk(sid: int, prefix: str, depth: int):
            stack = [sid]
            while stack:
                current = stack.pop()
                if current == _NOSTREAM or current >= len(self.entries) or current in seen or depth > 32:
                    continue
                seen.add(current)
                entry = self.entries[current]
                entry.path = f"{prefix}{entry.name}"
                stack.extend((entry.left, entry.right))
                if entry.is_storage and entry.child != _NOSTREAM:
                    walk(entry.child, entry.path + "/", depth + 1)

        seen.add(0)
        walk(self.entries[0].child, "", 0)

    def items(self) -> list[Entry]:
        return [e for e in self.entries[1:] if e.path]

    def find(self, path: str) -> Entry | None:
        for entry in self.entries[1:]:
            if entry.path == path:
                return entry
        return None

    def children(self, storage: str) -> list[Entry]:
        prefix = storage + "/" if storage else ""
        return [e for e in self.items() if e.path.startswith(prefix) and "/" not in e.path[len(prefix):]]

    def read(self, path_or_entry, limit: int = 100 * 1024 * 1024) -> bytes:
        entry = self.find(path_or_entry) if isinstance(path_or_entry, str) else path_or_entry
        if entry is None or entry.kind != 2:
            raise CfbError("스트림이 없습니다.")
        size = min(entry.size, limit)
        if entry.size < self.cutoff:
            return self._chain_bytes(entry.start, self.minifat, self.mini_sector, self._mini, limit=size)
        return self._chain_bytes(entry.start, self.fat, self.sector, self._sector, limit=size)
