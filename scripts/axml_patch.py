"""Patch strings / int attributes in a binary AndroidManifest.xml (AXML).

usage:
  python axml_patch.py <in.apk> <out-axml> [--set-string FROM TO] [--set-int ATTR VALUE]

Only the string pool and in-place 32-bit attribute values are rewritten, so the
rest of the manifest (resource map, element tree) stays byte-identical.
"""
import argparse
import struct
import sys
import zipfile

CHUNK_STRING_POOL = 0x0001
CHUNK_XML = 0x0003


def parse_pool(d, off):
    ctype, hsize, size = struct.unpack_from('<HHI', d, off)
    assert ctype == CHUNK_STRING_POOL, hex(ctype)
    count, style_count, flags, strings_start, styles_start = struct.unpack_from('<IIIII', d, off + 8)
    offsets = list(struct.unpack_from('<%dI' % count, d, off + hsize)) if count else []
    assert not style_count or styles_start, 'styled pools are not supported'
    utf8 = bool(flags & (1 << 8))
    strings = []
    for o in offsets:
        p = off + strings_start + o
        if utf8:
            # two lengths, then bytes
            n = d[p]
            p += 2 if (n & 0x80) else 1
            m = d[p]
            p += 2 if (m & 0x80) else 1
            strings.append(d[p:p + m].decode('utf-8', 'replace'))
        else:
            n = struct.unpack_from('<H', d, p)[0]
            p += 2
            strings.append(d[p:p + n * 2].decode('utf-16-le', 'replace'))
    return {
        'off': off, 'hsize': hsize, 'size': size, 'count': count, 'style_count': style_count,
        'flags': flags, 'strings_start': strings_start, 'styles_start': styles_start,
        'strings': strings, 'utf8': utf8,
    }


def build_pool(pool):
    """Rebuild the string pool chunk with (possibly) modified strings."""
    strings = pool['strings']
    data = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(data))
        if pool['utf8']:
            b = s.encode('utf-8')
            data += bytes([len(b)]) + b + b'\x00'
        else:
            data += struct.pack('<H', len(s)) + s.encode('utf-16-le') + b'\x00\x00'
        while len(data) % 4:
            data += b'\x00'
    strings_start = pool['hsize'] + 4 * len(strings) + 4 * pool['style_count']
    total = strings_start + len(data)
    out = bytearray()
    out += struct.pack('<HHI', CHUNK_STRING_POOL, pool['hsize'], total)
    out += struct.pack('<IIIII', len(strings), pool['style_count'], pool['flags'] & ~(1 << 0),
                       strings_start, 0)
    out += struct.pack('<%dI' % len(strings), *offsets)
    out += data
    return bytes(out)


def find_attr_chunks(d, pool, attr_name):
    """Yield (offset, data_offset) of every attribute named attr_name with a 32-bit int value."""
    name_idx = pool['strings'].index(attr_name) if attr_name in pool['strings'] else -1
    if name_idx < 0:
        return []
    res = []
    off = pool['off'] + pool['size']
    while off < len(d):
        ctype, hsize, size = struct.unpack_from('<HHI', d, off)
        if ctype == 0x0102:  # START_ELEMENT
            # ResXMLTree_node (16B) then ResXMLTree_attrExt
            attr_start = struct.unpack_from('<H', d, off + 24)[0]
            attr_count = struct.unpack_from('<H', d, off + 28)[0]
            base = off + 16 + attr_start
            for i in range(attr_count):
                a = base + i * 20
                ns, name, raw = struct.unpack_from('<III', d, a)
                if name == name_idx:
                    res.append(a + 16)  # typedValue.data
        off += size
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('apk')
    ap.add_argument('out')
    ap.add_argument('--set-string', nargs=2, action='append', default=[])
    ap.add_argument('--set-int', nargs=2, action='append', default=[])
    args = ap.parse_args()

    with zipfile.ZipFile(args.apk) as z:
        d = bytearray(z.read('AndroidManifest.xml'))

    ctype, xml_hsize, xml_size = struct.unpack_from('<HHI', d, 0)
    assert ctype == CHUNK_XML
    pool = parse_pool(d, xml_hsize)
    print(f'string pool: {pool["count"]} strings, utf8={pool["utf8"]}, size={pool["size"]}')

    changed = False
    for frm, to in args.set_string:
        hits = [i for i, s in enumerate(pool['strings']) if s == frm]
        print(f'--set-string {frm!r} -> {to!r}: {len(hits)} hit(s) at idx {hits}')
        for i in hits:
            pool['strings'][i] = to
            changed = True

    # rebuild pool first so offsets for the int patch stay valid (int patch is in place anyway)
    if changed:
        new_pool = build_pool(pool)
        rest = bytes(d[pool['off'] + pool['size']:])
        d = bytearray(struct.pack('<HHI', CHUNK_XML, xml_hsize, xml_hsize + len(new_pool) + len(rest))
                      + new_pool + rest)
        pool = parse_pool(d, xml_hsize)
        print(f'new pool size {pool["size"]}, file size {len(d)}')

    for attr, val in args.set_int:
        for data_off in find_attr_chunks(d, pool, attr):
            old = struct.unpack_from('<I', d, data_off)[0]
            struct.pack_into('<I', d, data_off, int(val))
            print(f'--set-int {attr}: {old} -> {val}')
            changed = True

    if not changed:
        print('nothing changed')
    with open(args.out, 'wb') as f:
        f.write(d)
    print('written:', args.out, len(d))


if __name__ == '__main__':
    main()
