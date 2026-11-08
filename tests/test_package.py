import io
import struct
import zipfile

import pytest

from workroom.workroom_core.ooxml.package import PackageError, compare, open_package, raw_unchanged, rewrite


def _sample_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Revenue grew 12%"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    box.text_frame.text = "Total 1,234"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _zip_with(entries: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_rewrite_without_edits_is_byte_identical() -> None:
    original = _sample_pptx()
    pkg = open_package(original)
    assert rewrite(pkg, {}) == original


def test_replaced_entry_changes_only_that_entry() -> None:
    original = _sample_pptx()
    pkg = open_package(original)
    target = "ppt/slides/slide1.xml"
    new_xml = pkg.read(target).replace(b"1,234", b"1,300")
    out = rewrite(pkg, {target: new_xml})
    after = open_package(out)
    report = compare(pkg, after)
    assert report.changed == (target,)
    assert not report.added and not report.removed
    others = [n for n in pkg.names() if n != target]
    assert raw_unchanged(pkg, after, others) == others
    assert zipfile.ZipFile(io.BytesIO(out)).testzip() is None


def test_result_opens_in_python_pptx() -> None:
    from pptx import Presentation

    original = _sample_pptx()
    pkg = open_package(original)
    target = "ppt/slides/slide1.xml"
    out = rewrite(pkg, {target: pkg.read(target).replace(b"1,234", b"1,300")})
    prs = Presentation(io.BytesIO(out))
    texts = [s.text_frame.text for s in prs.slides[0].shapes if s.has_text_frame]
    assert "Total 1,300" in texts


@pytest.mark.parametrize("name", ["../evil.xml", "/abs.xml", "a/../../b.xml", "C:/x.xml"])
def test_unsafe_names_are_refused(name: str) -> None:
    with pytest.raises(PackageError):
        open_package(_zip_with({name: b"x"}))


def test_backslash_name_is_refused_by_the_validator() -> None:
    from workroom.workroom_core.ooxml.package import _validate_name

    with pytest.raises(PackageError):
        _validate_name("a" + chr(92) + "b.xml")


def test_duplicate_names_are_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.xml", b"1")
        with pytest.warns(UserWarning):
            z.writestr("a.xml", b"2")
    with pytest.raises(PackageError):
        open_package(buf.getvalue())


def test_compression_bomb_is_refused() -> None:
    data = _zip_with({"big.xml": b"0" * (50 * 1024 * 1024)})
    with pytest.raises(PackageError):
        open_package(data)


def test_not_a_zip_is_refused() -> None:
    with pytest.raises(PackageError):
        open_package(b"this is not a package")


def test_encrypted_flag_is_refused() -> None:
    data = bytearray(_zip_with({"a.xml": b"hello"}))
    cd = data.rfind(struct.pack("<I", 0x02014B50))
    flags = struct.unpack_from("<H", data, cd + 8)[0]
    struct.pack_into("<H", data, cd + 8, flags | 0x1)
    with pytest.raises(PackageError):
        open_package(bytes(data))


def test_corrupt_data_fails_crc_on_read() -> None:
    data = bytearray(_zip_with({"a.xml": b"hello world" * 10}, zipfile.ZIP_STORED))
    idx = data.find(b"hello world")
    data[idx] ^= 0xFF
    pkg = open_package(bytes(data))
    with pytest.raises(PackageError):
        pkg.read("a.xml")


def test_replace_missing_and_add_existing_are_refused() -> None:
    pkg = open_package(_zip_with({"a.xml": b"1"}))
    with pytest.raises(PackageError):
        rewrite(pkg, {"nope.xml": b"x"})
    with pytest.raises(PackageError):
        rewrite(pkg, {}, {"a.xml": b"x"})


def test_additions_are_appended_and_readable() -> None:
    pkg = open_package(_zip_with({"a.xml": b"1"}))
    out = open_package(rewrite(pkg, {}, {"b.xml": b"2"}))
    assert out.names() == ["a.xml", "b.xml"]
    assert out.read("b.xml") == b"2"
