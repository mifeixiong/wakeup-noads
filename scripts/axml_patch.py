"""Patch strings / int attributes in a binary AndroidManifest.xml (AXML).

只重写字符串池与 32 位整型属性值，manifest 其余部分（资源映射、元素树）保持字节不变。

审核加固（P2-5）：
  * 每处修改都要求**恰好命中一次**，0 次或多次一律失败（可用 --allow-zero 显式放宽）；
  * 返回结构化报告，供构建脚本汇总进 build-report.json；
  * 提供 patch_manifest() 供其他脚本直接调用，CLI 只是薄封装。

usage:
  python axml_patch.py <in.apk> <out-axml> [--set-string FROM TO] [--set-int ATTR VALUE]
"""
import argparse
import struct
import sys
import zipfile

CHUNK_STRING_POOL = 0x0001
CHUNK_XML = 0x0003


class AxmlPatchError(RuntimeError):
    pass


def parse_pool(d, off):
    ctype, hsize, size = struct.unpack_from('<HHI', d, off)
    if ctype != CHUNK_STRING_POOL:
        raise AxmlPatchError(f'期望字符串池 chunk，实际 0x{ctype:04x}')
    count, style_count, flags, strings_start, styles_start = struct.unpack_from('<IIIII', d, off + 8)
    offsets = list(struct.unpack_from('<%dI' % count, d, off + hsize)) if count else []
    if style_count and not styles_start:
        raise AxmlPatchError('带样式数据的字符串池暂不支持')
    utf8 = bool(flags & (1 << 8))
    strings = []
    for o in offsets:
        p = off + strings_start + o
        if utf8:
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
    """按当前 strings 重建字符串池 chunk。"""
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
    """返回该属性全部 32 位值的写入偏移（typedValue.data）。"""
    if attr_name not in pool['strings']:
        return []
    name_idx = pool['strings'].index(attr_name)
    res = []
    off = pool['off'] + pool['size']
    while off + 8 <= len(d):
        ctype, hsize, size = struct.unpack_from('<HHI', d, off)
        if size <= 0:
            break
        if ctype == 0x0102:  # START_ELEMENT
            attr_start = struct.unpack_from('<H', d, off + 24)[0]
            attr_count = struct.unpack_from('<H', d, off + 28)[0]
            base = off + 16 + attr_start
            for i in range(attr_count):
                a = base + i * 20
                ns, name, raw = struct.unpack_from('<III', d, a)
                if name == name_idx:
                    res.append(a + 16)
        off += size
    return res


def read_manifest_strings(apk) -> list:
    with zipfile.ZipFile(apk) as z:
        d = z.read('AndroidManifest.xml')
    ctype, hsize, _ = struct.unpack_from('<HHI', d, 0)
    if ctype != CHUNK_XML:
        raise AxmlPatchError('AndroidManifest.xml 不是二进制 XML')
    return parse_pool(d, hsize)['strings']


def read_attrs(apk, names) -> dict:
    """读回指定属性的值（字符串型返回字符串，整型返回 int），用于产物自检。"""
    with zipfile.ZipFile(apk) as z:
        d = bytearray(z.read('AndroidManifest.xml'))
    ctype, hsize, _ = struct.unpack_from('<HHI', d, 0)
    pool = parse_pool(d, hsize)
    out = {}
    for name in names:
        for data_off in find_attr_chunks(d, pool, name):
            rec = data_off - 16
            ns, nm, raw, tsize, res0, dtype, data = struct.unpack_from('<IIIHBBI', d, rec)
            out[name] = pool['strings'][data] if dtype == 0x03 else data
    return out


def patch_manifest(in_apk, out_axml, set_string=(), set_int=(), *, expect_once=True,
                   allow_zero=False) -> dict:
    """改写 manifest 并返回 {'strings': [...], 'ints': [...], 'size': n}。

    每处修改要求恰好命中一次；不满足时抛 AxmlPatchError（除非 allow_zero 且命中 0 次）。
    """
    with zipfile.ZipFile(in_apk) as z:
        d = bytearray(z.read('AndroidManifest.xml'))

    ctype, xml_hsize, xml_size = struct.unpack_from('<HHI', d, 0)
    if ctype != CHUNK_XML:
        raise AxmlPatchError('AndroidManifest.xml 不是二进制 XML')
    pool = parse_pool(d, xml_hsize)

    report = {'strings': [], 'ints': [], 'size': len(d), 'expect_once': bool(expect_once)}
    changed = False

    for frm, to in set_string:
        hits = [i for i, s in enumerate(pool['strings']) if s == frm]
        report['strings'].append({'from': frm, 'to': to, 'hits': len(hits)})
        if len(hits) == 0 and not allow_zero:
            raise AxmlPatchError(f'字符串 {frm!r} 在 manifest 字符串池里没有命中（期望 1 次）')
        if expect_once and len(hits) > 1:
            raise AxmlPatchError(f'字符串 {frm!r} 命中 {len(hits)} 次（期望 1 次），请改为更精确的值')
        for i in hits:
            pool['strings'][i] = to
            changed = True

    if changed:
        new_pool = build_pool(pool)
        rest = bytes(d[pool['off'] + pool['size']:])
        d = bytearray(struct.pack('<HHI', CHUNK_XML, xml_hsize,
                                  xml_hsize + len(new_pool) + len(rest)) + new_pool + rest)
        pool = parse_pool(d, xml_hsize)
        report['size'] = len(d)

    for attr, val in set_int:
        offsets = find_attr_chunks(d, pool, attr)
        old_values = [struct.unpack_from('<I', d, o)[0] for o in offsets]
        report['ints'].append({'attr': attr, 'value': int(val), 'hits': len(offsets),
                               'old': old_values})
        if len(offsets) == 0 and not allow_zero:
            raise AxmlPatchError(f'属性 {attr!r} 在 manifest 里没有命中（期望 1 次）')
        if expect_once and len(offsets) > 1:
            raise AxmlPatchError(f'属性 {attr!r} 命中 {len(offsets)} 次（期望 1 次）')
        for o in offsets:
            struct.pack_into('<I', d, o, int(val))

    with open(out_axml, 'wb') as f:
        f.write(d)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('apk')
    ap.add_argument('out')
    ap.add_argument('--set-string', nargs=2, action='append', default=[])
    ap.add_argument('--set-int', nargs=2, action='append', default=[])
    ap.add_argument('--allow-zero', action='store_true', help='允许某处修改命中 0 次')
    ap.add_argument('--no-expect-once', action='store_true', help='不要求恰好一次（默认要求）')
    args = ap.parse_args()
    try:
        rep = patch_manifest(args.apk, args.out, args.set_string, args.set_int,
                             expect_once=not args.no_expect_once, allow_zero=args.allow_zero)
    except AxmlPatchError as e:
        print(f'错误: {e}', file=sys.stderr)
        return 1
    for s in rep['strings']:
        print(f"--set-string {s['from']!r} -> {s['to']!r}: 命中 {s['hits']} 次")
    for i in rep['ints']:
        print(f"--set-int {i['attr']}: {i['old']} -> {i['value']}（命中 {i['hits']} 次）")
    print(f'written: {args.out} ({rep["size"]} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
