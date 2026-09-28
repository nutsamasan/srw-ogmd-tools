"""The user-confirmed Triangle backlog margin, scoped to its nine text widgets.

Recognize the supported version-16 WTD window and widget/state headers rather
than searching/replacing width values globally. Text payloads may be localized.
"""
import struct

ENTRY = '/Dat/Window/WindowToolData/windowdataMain.wtd'
ARCHIVE = 'General2d'
WIDTH = 720
FEATURE = 'Triangle backlog text leaves space before the scrollbar'
_HEADER = bytes.fromhex(
    '00000140000036c70000000900000000000000000000000000000000ffffffff'
    '000000010000000000000000000000000000000000000000ffffffff0000000000000004')
_SKIN = struct.pack('>I', 13) + b'kihon_center\0'.ljust(16, b'\0')


def patch_backlog(data):
    """Return a separate asset and review; fixed inputs return identical bytes."""
    if data[:8] != b'_DTW\0\0\0\x10':
        raise ValueError('Unsupported window layout version for the backlog fix.')
    offset = 0x718
    windows = []
    for _ in range(403):
        if offset + 8 > len(data):
            raise ValueError('Truncated window layout.')
        size, identifier = struct.unpack_from('>II', data, offset)
        if size < 24 or offset + size > len(data):
            raise ValueError('Invalid window layout bounds.')
        if identifier == 0x6048cafb:  # Native name hash of BackLog.
            windows.append((offset, offset + size))
        offset += size
    if len(windows) != 1:
        raise ValueError('The supported BackLog window was not found uniquely.')
    start, end = windows[0]
    fields = []
    for number in range(1, 10):
        header = bytearray(_HEADER)
        struct.pack_into('>I', header, 4, 0x36c6 + number)
        at = data.find(header, start, end)
        if at < 0 or data.find(header, at + 1, end) >= 0:
            raise ValueError(f'Unsupported or ambiguous backlog widget f{number}.')
        prefix = struct.pack('>I', 0x8945 if number == 1 else 0xc945) + _SKIN
        if number > 1:
            prefix += struct.pack('>f', 36.0 * (number - 1))
        prefix += struct.pack('>ff', 28.0, 28.0)
        prop = at + len(header)
        width_at = prop + len(prefix)
        if width_at + 4 > end or data[prop:width_at] != prefix:
            raise ValueError(f'Backlog f{number} has an unsupported text layout.')
        width, following = struct.unpack_from('>HH', data, width_at)
        if width not in (740, WIDTH) or following != 0xffff:
            raise ValueError(f'Backlog f{number} has an unexpected width; no layout was changed.')
        fields.append((number, width_at, width))
    if [p for _, p, _ in fields] != sorted(p for _, p, _ in fields):
        raise ValueError('Unexpected backlog widget order.')
    output = bytearray(data)
    changes = []
    for number, at, before in fields:
        if before != WIDTH:
            struct.pack_into('>H', output, at, WIDTH)
            changes.append(dict(widget=f'f{number}', offset=at, before=before, after=WIDTH))
    return bytes(output), dict(kind='backlog-margin', archive=ARCHIVE, entry=ENTRY,
                              width=WIDTH, changed_widgets=len(changes),
                              already_applied=not changes, changes=changes)


def patch_archives(groups, backlog):
    return sorted({name for name, _ in groups} | ({ARCHIVE} if backlog else set()))
