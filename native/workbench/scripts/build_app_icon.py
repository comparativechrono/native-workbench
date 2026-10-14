#!/usr/bin/env python3
"""Build the native application icon from its small geometric SVG source.

Only the SVG primitives used by desktop/assets/native-workbench.svg are accepted:
solid circles, solid rounded rectangles, and round-capped/joined polylines. This
is deliberately not a general SVG renderer. Unsupported artwork fails the build
instead of silently rendering differently. Supersampling, PNG and ICO encoding
use only the Python standard library; no graphics runtime is added to the app.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zlib

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SVG_NS = '{http://www.w3.org/2000/svg}'


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Icon coordinates must be finite')
    return result


def colour(value):
    if len(value) != 7 or not value.startswith('#'):
        raise ValueError('Icon colours must use #RRGGBB')
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def artwork(path):
    root = ET.parse(path).getroot()
    if root.tag != SVG_NS + 'svg' or root.get('viewBox') != '0 0 128 128':
        raise ValueError('Icon SVG must have a 0 0 128 128 viewBox')
    if set(root.attrib) - {'width', 'height', 'viewBox', 'role', 'aria-labelledby'}:
        raise ValueError('Unsupported icon SVG root attribute')
    shapes = []
    for element in root:
        if element.tag in (SVG_NS + 'title', SVG_NS + 'desc'):
            continue
        tag = element.tag.removeprefix(SVG_NS)
        attrs = element.attrib
        if list(element):
            raise ValueError('Icon SVG shapes cannot contain children')
        if tag == 'rect':
            allowed = {'x', 'y', 'width', 'height', 'rx', 'fill'}
            x, y, w, h, r = (number(attrs[k]) for k in ('x', 'y', 'width', 'height', 'rx'))
            if w <= 0 or h <= 0 or r < 0 or r > min(w, h) / 2:
                raise ValueError('Invalid rounded rectangle')

            def contains(px, py, x=x, y=y, w=w, h=h, r=r):
                if not x <= px <= x + w or not y <= py <= y + h:
                    return False
                dx = max(x + r - px, 0, px - (x + w - r))
                dy = max(y + r - py, 0, py - (y + h - r))
                return dx * dx + dy * dy <= r * r

            bounds = (x, y, x + w, y + h)
            fill = colour(attrs['fill'])
        elif tag == 'circle':
            allowed = {'cx', 'cy', 'r', 'fill'}
            x, y, r = (number(attrs[k]) for k in ('cx', 'cy', 'r'))
            if r <= 0:
                raise ValueError('Invalid circle')

            def contains(px, py, x=x, y=y, r=r):
                return (px - x) ** 2 + (py - y) ** 2 <= r * r

            bounds = (x - r, y - r, x + r, y + r)
            fill = colour(attrs['fill'])
        elif tag == 'polyline':
            allowed = {'points', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin'}
            if (attrs.get('fill'), attrs.get('stroke-linecap'), attrs.get('stroke-linejoin')) != ('none', 'round', 'round'):
                raise ValueError('Icon polylines require no fill and round caps/joins')
            coordinates = [number(v) for v in attrs['points'].replace(',', ' ').split()]
            if len(coordinates) < 4 or len(coordinates) % 2:
                raise ValueError('Invalid polyline points')
            points = list(zip(coordinates[::2], coordinates[1::2]))
            segments = []
            for (x, y), (end_x, end_y) in zip(points, points[1:]):
                dx, dy = end_x - x, end_y - y
                length = dx * dx + dy * dy
                if not length:
                    raise ValueError('Icon polyline cannot have zero-length segments')
                segments.append((x, y, dx, dy, length))
            r = number(attrs['stroke-width']) / 2
            if r <= 0:
                raise ValueError('Invalid polyline stroke')

            def contains(px, py, segments=segments, r=r):
                for x, y, dx, dy, length in segments:
                    t = max(0, min(1, ((px - x) * dx + (py - y) * dy) / length))
                    if (px - x - t * dx) ** 2 + (py - y - t * dy) ** 2 <= r * r:
                        return True
                return False

            bounds = (min(x for x, _ in points) - r, min(y for _, y in points) - r,
                      max(x for x, _ in points) + r, max(y for _, y in points) + r)
            fill = colour(attrs['stroke'])
        else:
            raise ValueError('Unsupported icon SVG element: ' + tag)
        if set(attrs) - allowed:
            raise ValueError('Unsupported icon SVG attribute: ' + tag)
        shapes.append((contains, bounds, fill))
    if not shapes:
        raise ValueError('Icon SVG has no shapes')
    return shapes


def rasterize(shapes, size, samples=4):
    """Return straight-alpha RGBA pixels, averaging premultiplied samples."""
    if not 1 <= size <= 1024 or not 1 <= samples <= 8:
        raise ValueError('Invalid icon raster dimensions')
    resolution = size * samples
    canvas = bytearray(resolution * resolution * 4)
    scale = resolution / 128
    for contains, bounds, fill in shapes:
        left, top, right, bottom = bounds
        pixel = bytes((*fill, 255))
        for y in range(max(0, math.floor(top * scale)), min(resolution, math.ceil(bottom * scale))):
            py = (y + .5) / scale
            for x in range(max(0, math.floor(left * scale)), min(resolution, math.ceil(right * scale))):
                if contains((x + .5) / scale, py):
                    offset = (y * resolution + x) * 4
                    canvas[offset:offset + 4] = pixel
    result = bytearray(size * size * 4)
    count = samples * samples
    for y in range(size):
        for x in range(size):
            red = green = blue = opaque = 0
            for dy in range(samples):
                start = ((y * samples + dy) * resolution + x * samples) * 4
                for dx in range(samples):
                    offset = start + dx * 4
                    if canvas[offset + 3]:
                        red += canvas[offset]
                        green += canvas[offset + 1]
                        blue += canvas[offset + 2]
                        opaque += 1
            if opaque:
                offset = (y * size + x) * 4
                result[offset:offset + 4] = bytes(((red + opaque // 2) // opaque,
                                                  (green + opaque // 2) // opaque,
                                                  (blue + opaque // 2) // opaque,
                                                  (opaque * 255 + count // 2) // count))
    return bytes(result)


def png(size, pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


def dib(size, pixels):
    """32-bit BGRA DIB and legacy AND mask, both stored bottom-up."""
    colour_bytes = bytearray()
    mask = bytearray()
    stride = ((size + 31) // 32) * 4
    for y in reversed(range(size)):
        mask_row = bytearray(stride)
        for x in range(size):
            offset = (y * size + x) * 4
            red, green, blue, alpha = pixels[offset:offset + 4]
            colour_bytes.extend((blue, green, red, alpha))
            if not alpha:
                mask_row[x // 8] |= 0x80 >> (x % 8)
        mask.extend(mask_row)
    return struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, len(colour_bytes), 0, 0, 0, 0) + colour_bytes + mask


def icon(shapes):
    images = []
    for size in SIZES:
        pixels = rasterize(shapes, size)
        images.append(png(size, pixels) if size >= 128 else dib(size, pixels))
    offset = 6 + len(images) * 16
    entries = bytearray()
    for size, data in zip(SIZES, images):
        entries.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    return struct.pack('<HHH', 0, 1, len(images)) + entries + b''.join(images)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--svg', type=Path, default=Path('desktop/assets/native-workbench.svg'))
    parser.add_argument('--ico', type=Path, default=Path('build/desktop/native-workbench.ico'))
    parser.add_argument('--preview', type=Path, help='Optional transparent 256-pixel PNG preview')
    args = parser.parse_args()
    shapes = artwork(args.svg)
    args.ico.parent.mkdir(parents=True, exist_ok=True)
    args.ico.write_bytes(icon(shapes))
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        args.preview.write_bytes(png(256, rasterize(shapes, 256)))
    print(f'Built {args.ico} from {args.svg} ({len(SIZES)} icon sizes)')


if __name__ == '__main__':
    main()
