"""Read start/end timestamps from a ROS bag — pure Python, no ROS imports.

Parses the ROS bag v2.0 binary format directly:
    - 13-byte magic ``#ROSBAG V2.0\\n``
    - bag-header record (``op=0x03``) with ``index_pos`` and ``chunk_count``
    - chunk-info records (``op=0x06``) at ``index_pos``, each carrying
      ``start_time`` and ``end_time`` as ``(sec uint32, nsec uint32)``

For ``.bag.active`` (and any other unindexed bag), falls back to scanning
chunk records from the start, reading message-data records inside. Only
works on uncompressed unindexed bags — which is the default ``rosbag record``
configuration; compressed unindexed bags raise :class:`BagInspectionError`.

Reference: https://wiki.ros.org/Bags/Format/2.0
"""
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, NamedTuple, Tuple


class BagTimeRange(NamedTuple):
    """Bag-internal start/end as UTC-aware datetimes.

    Bag-internal timestamps are Unix-epoch seconds (UTC by definition,
    regardless of the recording host's clock). Producing UTC-aware values
    here keeps the rest of the pipeline independent of the host TZ.
    """
    start: datetime
    end: datetime


class BagInspectionError(RuntimeError):
    """Raised when a bag's metadata cannot be read."""


_MAGIC = b"#ROSBAG V2.0\n"
_OP_MESSAGE_DATA = 0x02
_OP_BAG_HEADER = 0x03
_OP_CHUNK = 0x05
_OP_CHUNK_INFO = 0x06


def _read_u32(f) -> int:
    b = f.read(4)
    if len(b) < 4:
        raise BagInspectionError("unexpected EOF reading uint32")
    return struct.unpack("<I", b)[0]


def _read_record_header(f) -> Tuple[Dict[str, bytes], int, int]:
    """Read one record. Returns ``(fields, data_len, data_pos)``.

    File position after this call is at the start of the data section. The
    caller is expected to either consume that data or seek past it.
    """
    header_len = _read_u32(f)
    header_data = f.read(header_len)
    if len(header_data) < header_len:
        raise BagInspectionError("unexpected EOF reading record header")
    fields: Dict[str, bytes] = {}
    pos = 0
    while pos < header_len:
        if pos + 4 > header_len:
            raise BagInspectionError("malformed header field length")
        field_len = struct.unpack_from("<I", header_data, pos)[0]
        pos += 4
        if pos + field_len > header_len:
            raise BagInspectionError("malformed header field payload")
        field = header_data[pos:pos + field_len]
        pos += field_len
        eq = field.find(b"=")
        if eq < 0:
            raise BagInspectionError("header field missing '='")
        name = field[:eq].decode("ascii", "replace")
        value = field[eq + 1:]
        fields[name] = value
    data_len = _read_u32(f)
    return fields, data_len, f.tell()


def _op(fields: Dict[str, bytes]) -> int:
    op = fields.get("op")
    if op is None or len(op) != 1:
        raise BagInspectionError("record missing or malformed 'op' field")
    return op[0]


def _parse_time(b: bytes) -> datetime:
    if len(b) != 8:
        raise BagInspectionError("'time' field must be 8 bytes")
    sec, nsec = struct.unpack("<II", b)
    return datetime.fromtimestamp(sec + nsec * 1e-9, tz=timezone.utc)


def inspect_bag(bag_path: Path) -> BagTimeRange:
    """Return ``(start, end)`` datetimes for the given bag.

    Raises :class:`BagInspectionError` if the file is not a v2.0 ROS bag,
    is truncated/corrupt, or has no message data to derive a time range
    from. ``.bag.active`` files are supported via the unindexed-scan path.
    """
    bag_path = Path(bag_path)
    try:
        with open(bag_path, "rb") as f:
            magic = f.read(len(_MAGIC))
            if magic != _MAGIC:
                raise BagInspectionError(
                    f"not a ROS bag v2.0 (bad magic): {bag_path}"
                )

            fields, data_len, data_pos = _read_record_header(f)
            if _op(fields) != _OP_BAG_HEADER:
                raise BagInspectionError("first record is not the bag header")
            index_pos_b = fields.get("index_pos")
            chunk_count_b = fields.get("chunk_count")
            if index_pos_b is None or chunk_count_b is None:
                raise BagInspectionError(
                    "bag header missing 'index_pos' or 'chunk_count'"
                )
            index_pos = struct.unpack("<Q", index_pos_b)[0]
            chunk_count = struct.unpack("<I", chunk_count_b)[0]
            # Skip the bag-header data (zero padding).
            f.seek(data_pos + data_len)

            if chunk_count > 0 and index_pos > 0:
                return _inspect_via_index(f, index_pos, chunk_count)
            return _inspect_via_scan(f)
    except BagInspectionError:
        raise
    except OSError as e:
        raise BagInspectionError(f"cannot open {bag_path}: {e}") from e
    except Exception as e:
        raise BagInspectionError(f"failed to inspect {bag_path}: {e}") from e


def _inspect_via_index(f, index_pos: int, chunk_count: int) -> BagTimeRange:
    """Fast path: jump to the index and read chunk-info records."""
    f.seek(index_pos)
    starts = []
    ends = []
    seen = 0
    while seen < chunk_count:
        try:
            fields, data_len, data_pos = _read_record_header(f)
        except BagInspectionError:
            break
        if _op(fields) == _OP_CHUNK_INFO:
            start_b = fields.get("start_time")
            end_b = fields.get("end_time")
            if start_b is None or end_b is None:
                raise BagInspectionError(
                    "chunk_info missing 'start_time' or 'end_time'"
                )
            starts.append(_parse_time(start_b))
            ends.append(_parse_time(end_b))
            seen += 1
        f.seek(data_pos + data_len)
    if not starts:
        raise BagInspectionError("no chunk_info records found at index_pos")
    return BagTimeRange(start=min(starts), end=max(ends))


def _inspect_via_scan(f) -> BagTimeRange:
    """Fallback for unindexed bags (e.g. ``.bag.active``).

    Walks every chunk and every message-data record inside, tracking min/max
    of message timestamps. Refuses compressed unindexed bags.
    """
    starts = []
    ends = []
    while True:
        try:
            fields, data_len, data_pos = _read_record_header(f)
        except BagInspectionError:
            break  # treat as EOF / truncation
        op = _op(fields)
        if op == _OP_CHUNK:
            compression = fields.get("compression", b"").decode("ascii", "replace")
            if compression and compression != "none":
                raise BagInspectionError(
                    f"unindexed bag with compression={compression!r} "
                    "is not supported by the pure-Python parser"
                )
            chunk_end = data_pos + data_len
            while f.tell() < chunk_end:
                try:
                    inner_fields, inner_data_len, inner_data_pos = _read_record_header(f)
                except BagInspectionError:
                    break
                if _op(inner_fields) == _OP_MESSAGE_DATA:
                    time_b = inner_fields.get("time")
                    if time_b is not None:
                        t = _parse_time(time_b)
                        starts.append(t)
                        ends.append(t)
                f.seek(inner_data_pos + inner_data_len)
            f.seek(chunk_end)
        else:
            f.seek(data_pos + data_len)
    if not starts:
        raise BagInspectionError(
            "no message-data records found while scanning unindexed bag"
        )
    return BagTimeRange(start=min(starts), end=max(ends))
