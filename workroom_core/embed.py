"""Carry a signed release record inside a Word, PowerPoint or Excel file, and read it back.

The record is stored the way Office stores its own custom XML data: an item part (``customXml/item_workroom.xml``) with a properties part, related from the
main document part. Embedding changes the file's bytes, so the record cannot name the file's SHA-256; it names a *package digest* instead: a hash over every
part except the proof parts, with the two files embedding edits (the main part's relationship list and the content-type list) read as if the proof had never
been added. A copy that carries a record can therefore be checked on its own, and the original released file (without the record) has the same digest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from lxml import etree

from .ooxml.package import Package, open_package, rewrite

PART = "customXml/item_workroom.xml"
PROPS = "customXml/itemProps_workroom.xml"
ITEM_RELS = "customXml/_rels/item_workroom.xml.rels"
OURS = {PART, PROPS, ITEM_RELS}
NS = "urn:workroom:proof:1"
ITEM_ID = "{7C0D5A1E-3B64-4F5B-9A53-5D0E2C6B7A11}"
CUSTOM_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
PROPS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
PROPS_TYPE = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
_ROOT_RELS = "_rels/.rels"
_TYPES = "[Content_Types].xml"
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)
_REL_URI = "http://schemas.openxmlformats.org/package/2006/relationships"
_RELNS = "{" + _REL_URI + "}"
_CTNS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + chr(10)


def _main_part(pkg: Package) -> str:
    for rel in etree.fromstring(pkg.read(_ROOT_RELS), _PARSER):
        if (rel.get("Type") or "").endswith("/officeDocument"):
            return (rel.get("Target") or "").lstrip("/")
    raise ValueError("not an Office package")


def _rels_of(part: str) -> str:
    folder, _, name = part.rpartition("/")
    return f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels"


def _strip_proof(data: bytes) -> bytes:
    """A relationship or content-type list as it was before a record was embedded."""
    root = etree.fromstring(data, _PARSER)
    for el in list(root):
        target = (el.get("Target") or el.get("PartName") or "").lstrip("/")
        if target.endswith(("item_workroom.xml", "itemProps_workroom.xml")):
            root.remove(el)
    return etree.tostring(root, method="c14n")


def package_digest(data: bytes) -> str:
    """SHA-256 over every part's name and content, the embedded proof left out and its bookkeeping edits undone."""
    pkg = open_package(data)
    main_rels = _rels_of(_main_part(pkg))
    h = hashlib.sha256()
    for name in sorted(n for n in pkg.names() if n not in OURS and not n.endswith("/")):
        body = pkg.read(name)
        if name in (main_rels, _TYPES):
            body = _strip_proof(body)
        h.update(name.encode("utf-8") + bytes([0]) + hashlib.sha256(body).digest())
    return h.hexdigest()


def _xml(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def embed(data: bytes, envelope: dict[str, Any]) -> bytes:
    """The same package with the signed record added; a record already there is replaced. Every part but two bookkeeping lists keeps its bytes."""
    pkg = open_package(data)
    main = _main_part(pkg)
    main_rels = _rels_of(main)
    blob = base64.b64encode(json.dumps(envelope, sort_keys=True).encode("utf-8")).decode("ascii")
    item = (_DECL + f'<workroomProof xmlns="{NS}">{blob}</workroomProof>').encode("utf-8")
    props = (_DECL + f'<ds:datastoreItem ds:itemID="{ITEM_ID}" xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml">'
             f'<ds:schemaRefs><ds:schemaRef ds:uri="{NS}"/></ds:schemaRefs></ds:datastoreItem>').encode("utf-8")
    item_rels = (_DECL + f'<Relationships xmlns="{_REL_URI}"><Relationship Id="rId1" Type="{PROPS_REL}" Target="itemProps_workroom.xml"/></Relationships>').encode("utf-8")
    target = "../" * main.count("/") + PART
    had_rels = main_rels in pkg.by_name
    if had_rels:
        rels = etree.fromstring(_strip_proof(pkg.read(main_rels)), _PARSER)
    else:
        rels = etree.Element(f"{_RELNS}Relationships", nsmap={None: _REL_URI})
    used = {r.get("Id") for r in rels}
    rid = next(f"rIdWorkroom{n}" for n in range(1, 1000) if f"rIdWorkroom{n}" not in used)
    etree.SubElement(rels, f"{_RELNS}Relationship", Id=rid, Type=CUSTOM_REL, Target=target)
    types = etree.fromstring(_strip_proof(pkg.read(_TYPES)), _PARSER)
    etree.SubElement(types, f"{_CTNS}Override", PartName="/" + PROPS, ContentType=PROPS_TYPE)
    if not any(d.get("Extension", "").lower() == "xml" for d in types.findall(f"{_CTNS}Default")):
        etree.SubElement(types, f"{_CTNS}Default", Extension="xml", ContentType="application/xml")
    replaced = {_TYPES: _xml(types)}
    added: dict[str, bytes] = {}
    (replaced if had_rels else added)[main_rels] = _xml(rels)
    for name, payload in ((PART, item), (PROPS, props), (ITEM_RELS, item_rels)):
        (replaced if name in pkg.by_name else added)[name] = payload
    return rewrite(pkg, replaced, added)


def extract(data: bytes) -> dict[str, Any] | None:
    """The record embedded in a file, or None when there is none or it cannot be read. Office renumbers custom XML parts when it saves, so the record is
    found by what it is, not by its name."""
    try:
        pkg: Package = open_package(data)
        for name in sorted(n for n in pkg.names() if n.startswith("customXml/") and n.endswith(".xml") and "/_rels/" not in n and "itemProps" not in n):
            root = etree.fromstring(pkg.read(name), _PARSER)
            if root.tag != "{" + NS + "}workroomProof":
                continue
            obj = json.loads(base64.b64decode(re.sub(r"\s+", "", root.text or "")))
            if isinstance(obj, dict):
                return obj
        return None
    except Exception:  # noqa: BLE001  a damaged or foreign file simply carries no record
        return None
