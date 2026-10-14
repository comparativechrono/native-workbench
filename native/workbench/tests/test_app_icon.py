"""Check the source-artwork-to-Windows-icon contract without graphics packages."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_app_icon', ROOT / 'scripts/build_app_icon.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
SOURCE = ROOT / 'desktop/assets/native-workbench.svg'


def decode_image(size, data):
    """Independent decoder for the two standard image encodings in this ICO."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, compressed, header = 8, bytearray(), None
        while offset < len(data):
            length = struct.unpack_from('>I', data, offset)[0]
            kind = data[offset + 4:offset + 8]
            body = data[offset + 8:offset + 8 + length]
            crc = struct.unpack_from('>I', data, offset + 8 + length)[0]
            assert zlib.crc32(kind + body) == crc
            if kind == b'IHDR':
                header = struct.unpack('>IIBBBBB', body)
            elif kind == b'IDAT':
                compressed.extend(body)
            offset += length + 12
        assert offset == len(data)
        assert header == (size, size, 8, 6, 0, 0, 0)
        raw = zlib.decompress(compressed)
        stride = size * 4 + 1
        assert len(raw) == stride * size
        assert all(raw[y * stride] == 0 for y in range(size))
        return b''.join(raw[y * stride + 1:(y + 1) * stride] for y in range(size))
    header = struct.unpack_from('<IiiHHIIiiII', data)
    assert header == (40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
    pixels = bytearray()
    for y in reversed(range(size)):
        for x in range(size):
            offset = 40 + (y * size + x) * 4
            blue, green, red, alpha = data[offset:offset + 4]
            pixels.extend((red, green, blue, alpha))
    stride = ((size + 31) // 32) * 4
    assert len(data) == 40 + size * size * 4 + stride * size
    for y in range(size):
        for x in range(size):
            offset = 40 + size * size * 4 + (size - 1 - y) * stride + x // 8
            transparent = bool(data[offset] & (0x80 >> (x % 8)))
            assert transparent == (pixels[(y * size + x) * 4 + 3] == 0)
    return bytes(pixels)


class AppIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shapes = BUILD.artwork(SOURCE)
        cls.encoded = BUILD.icon(cls.shapes)

    def test_all_nine_sizes_decode_with_correct_alpha_and_orientation(self):
        self.assertEqual(struct.unpack_from('<HHH', self.encoded), (0, 1, 9))
        offset = 6 + 9 * 16
        for index, size in enumerate((16, 20, 24, 32, 40, 48, 64, 128, 256)):
            with self.subTest(size=size):
                w, h, palette, reserved, planes, bits, length, start = struct.unpack_from('<BBBBHHII', self.encoded, 6 + index * 16)
                self.assertEqual((w or 256, h or 256, palette, reserved, planes, bits), (size, size, 0, 0, 1, 32))
                self.assertEqual(start, offset)
                pixels = decode_image(size, self.encoded[start:start + length])
                offset += length

                def sample(x, y):
                    location = (int(y * size / 128) * size + int(x * size / 128)) * 4
                    return tuple(pixels[location:location + 4])

                self.assertEqual(sample(0, 0), (0, 0, 0, 0))
                self.assertEqual(sample(64, 112), (32, 56, 78, 255))
                # The centre upper module must be above the lower teal modules.
                # At 16 px a node spans only two pixels; its centre pixel also
                # averages the curved antialiased edge rather than pure fill.
                self.assertGreater(sample(64, 40)[0], 200)
                self.assertGreater(sample(43, 88)[1], 175)
                self.assertLess(sample(43, 88)[0], 140)
                self.assertTrue(any(0 < pixels[i] < 255 for i in range(3, len(pixels), 4)))
        self.assertEqual(offset, len(self.encoded))

    def test_unsupported_svg_does_not_silently_change_artwork(self):
        text = SOURCE.read_text()
        variants = [text.replace('<rect ', '<rect transform="rotate(5)" ', 1),
                    text.replace('<circle ', '<ellipse ', 1),
                    text.replace('stroke-linecap="round"', 'stroke-linecap="square"'),
                    text.replace('r="8"', 'r="NaN"', 1)]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'invalid.svg'
            for variant in variants:
                with self.subTest(variant=variant[:120]):
                    source.write_text(variant)
                    with self.assertRaises(ValueError):
                        BUILD.artwork(source)

    def test_icon_build_repeats_exactly(self):
        self.assertEqual(self.encoded, BUILD.icon(BUILD.artwork(SOURCE)))


if __name__ == '__main__':
    unittest.main()
