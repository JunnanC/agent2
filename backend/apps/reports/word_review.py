"""Read bounded DOCX content and attach ordinary Word comments to its paragraphs."""

from collections.abc import Iterator
from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.dom import Node
from xml.dom.minidom import Document, Element, parseString
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from django.conf import settings

from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENT_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
PART = "word/document.xml"
COMMENTS = "word/comments.xml"
RELATIONSHIPS = "word/_rels/document.xml.rels"
CONTENT_TYPES = "[Content_Types].xml"
MAX_XML = 12 * 1024 * 1024
MAX_UNCOMPRESSED = 120 * 1024 * 1024


def _xml(content: bytes) -> Document:
    if len(content) > MAX_XML or b"<!doctype" in content.lower().replace(b"\x00", b""):
        raise ValueError("Unsupported Word XML")
    return parseString(content)


def _check(archive: ZipFile) -> None:
    entries = archive.infolist()
    if (
        len(entries) > 1000
        or sum(item.file_size for item in entries) > MAX_UNCOMPRESSED
        or len(set(archive.namelist())) != len(entries)
        or PART not in archive.namelist()
        or CONTENT_TYPES not in archive.namelist()
        or any(name.lower().endswith("vbaproject.bin") for name in archive.namelist())
    ):
        raise ValueError("Unsupported Word document")


def valid_docx(stream: Any) -> bool:
    from xml.parsers.expat import ExpatError

    try:
        with ZipFile(stream) as archive:
            _check(archive)
            root = _xml(archive.read(PART)).documentElement
            return (
                root.namespaceURI == WORD
                and root.localName == "document"
                and bool(root.getElementsByTagNameNS(WORD, "body"))
            )
    except (BadZipFile, ValueError, ExpatError, KeyError, OSError):
        return False
    finally:
        stream.seek(0)


def asset_bytes(asset: ObjectAsset) -> bytes:
    import hashlib

    stored = object_storage().open_object(
        bucket=asset.bucket,
        object_key=asset.object_key,
        version_id=asset.object_version,
    )
    try:
        content = stored.body.read(settings.REPORT_ATTACHMENT_MAX_BYTES + 1)
    finally:
        stored.body.close()
    if (
        len(content) != asset.size_bytes
        or hashlib.sha256(content).hexdigest() != asset.digest_sha256
    ):
        raise ValueError("Word asset digest mismatch")
    return content


def _paragraphs(document: Document) -> list[Element]:
    body = document.getElementsByTagNameNS(WORD, "body")[0]
    return list(body.getElementsByTagNameNS(WORD, "p"))


def _text(element: Element) -> str:
    return "".join(
        node.data
        for text in element.getElementsByTagNameNS(WORD, "t")
        for node in text.childNodes
        if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
    )


def _property(element: Element | None, name: str, attribute: str = "val") -> str:
    if element is None:
        return ""
    nodes = element.getElementsByTagNameNS(WORD, name)
    return nodes[0].getAttributeNS(WORD, attribute) if nodes else ""


def _child(node: Element, tag: str) -> Element | None:
    return next(
        (
            child
            for child in node.childNodes
            if child.nodeType == Node.ELEMENT_NODE
            and child.namespaceURI == WORD
            and child.localName == tag
        ),
        None,
    )


def _style_layout(archive: ZipFile) -> tuple[dict[str, Element], Element | None]:
    if "word/styles.xml" not in archive.namelist():
        return {}, None
    style_document = _xml(archive.read("word/styles.xml"))
    styles = {
        node.getAttributeNS(WORD, "styleId"): node
        for node in style_document.getElementsByTagNameNS(WORD, "style")
    }
    defaults = style_document.getElementsByTagNameNS(WORD, "docDefaults")
    return styles, defaults[0] if defaults else None


def _inherits(styles: dict[str, Element], style_id: str) -> Iterator[Element]:
    seen: set[str] = set()
    while style_id in styles and style_id not in seen:
        seen.add(style_id)
        style = styles[style_id]
        yield style
        style_id = _property(style, "basedOn")


def _size(values: list[Element | None]) -> str:
    for props in values:
        raw = _property(props, "sz")
        if raw.isdecimal() and len(raw) <= 8:
            return str(Decimal(raw) / 2)
    return ""


def document_paragraphs(content: bytes) -> list[dict[str, Any]]:
    with ZipFile(BytesIO(content)) as archive:
        _check(archive)
        document = _xml(archive.read(PART))
        styles, defaults = _style_layout(archive)
    default_style = next(
        (
            style_id
            for style_id, style in styles.items()
            if style.getAttributeNS(WORD, "type") == "paragraph"
            and style.getAttributeNS(WORD, "default") in {"1", "true"}
        ),
        "",
    )
    rows: list[dict[str, Any]] = []
    for number, paragraph in enumerate(_paragraphs(document), 1):
        paragraph_text = _text(paragraph).strip()
        if not paragraph_text:
            continue
        paragraph_style = _property(_child(paragraph, "pPr"), "pStyle") or default_style
        sizes: set[str] = set()
        for run in paragraph.getElementsByTagNameNS(WORD, "r"):
            if not _text(run).strip():
                continue
            properties = _child(run, "rPr")
            run_style = _property(properties, "rStyle")
            inherited = list(_inherits(styles, run_style)) + list(
                _inherits(styles, paragraph_style)
            )
            size = _size([properties, *(_child(style, "rPr") for style in inherited), defaults])
            if size:
                sizes.add(size)
        rows.append({"paragraph": number, "text": paragraph_text[:3000], "sizes_pt": sorted(sizes)})
    return rows


def _word(document: Document, tag: str, **attributes: str) -> Element:
    element = document.createElementNS(WORD, f"w:{tag}")
    for key, value in attributes.items():
        element.setAttributeNS(WORD, f"w:{key}", value)
    return element


def _paragraph(document: Document, text: str) -> Element:
    p = _word(document, "p")
    run = _word(document, "r")
    value = _word(document, "t")
    value.setAttribute("xml:space", "preserve")
    value.appendChild(document.createTextNode(text))
    run.appendChild(value)
    p.appendChild(run)
    return p


def _comments_xml(archive: ZipFile) -> tuple[Document, Document, Document]:
    comments = (
        _xml(archive.read(COMMENTS))
        if COMMENTS in archive.namelist()
        else _xml(
            f'<w:comments xmlns:w="{WORD}"/>'.encode(),
        )
    )
    types = _xml(archive.read(CONTENT_TYPES))
    rels = (
        _xml(archive.read(RELATIONSHIPS))
        if RELATIONSHIPS in archive.namelist()
        else _xml(
            f'<Relationships xmlns="{RELS}"/>'.encode(),
        )
    )
    relationship_nodes = rels.getElementsByTagNameNS(RELS, "Relationship")
    if not any(node.getAttribute("Type") == COMMENT_TYPE for node in relationship_nodes):
        used = {node.getAttribute("Id") for node in relationship_nodes}
        i = 1
        while f"rId{i}" in used:
            i += 1
        relationship = rels.createElementNS(RELS, "Relationship")
        for key, value in {"Id": f"rId{i}", "Target": "comments.xml", "Type": COMMENT_TYPE}.items():
            relationship.setAttribute(key, value)
        rels.documentElement.appendChild(relationship)
    elif not any(
        node.getAttribute("Type") == COMMENT_TYPE
        and node.getAttribute("Target") in {"comments.xml", "/word/comments.xml"}
        for node in relationship_nodes
    ):
        raise ValueError("Unsupported Word comments relationship")
    if not any(
        node.getAttribute("PartName") == "/" + COMMENTS
        for node in types.getElementsByTagNameNS(TYPES, "Override")
    ):
        override = types.createElementNS(TYPES, "Override")
        override.setAttribute("PartName", "/" + COMMENTS)
        override.setAttribute(
            "ContentType",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        )
        types.documentElement.appendChild(override)
    return comments, types, rels


def annotated_docx(
    content: bytes,
    *,
    entries: list[dict],
    signer: str,
    date: str,
    score: str,
    feedback: str,
) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(output, "w", ZIP_DEFLATED) as result:
        _check(original)
        document = _xml(original.read(PART))
        document.documentElement.setAttribute("xmlns:w", WORD)
        paragraphs = _paragraphs(document)
        body = document.getElementsByTagNameNS(WORD, "body")[0]
        comments, types, rels = _comments_xml(original)
        comments.documentElement.setAttribute("xmlns:w", WORD)
        comment_ids = [
            int(value)
            for node in comments.getElementsByTagNameNS(WORD, "comment")
            if (value := node.getAttributeNS(WORD, "id")).isdigit()
        ]
        next_id = max(comment_ids, default=-1) + 1
        for item in entries:
            index = item["paragraph"] - 1
            if index < 0 or index >= len(paragraphs):
                raise ValueError("Comment paragraph is outside Word document")
            p = paragraphs[index]
            ident = str(next_id)
            next_id += 1
            start = _word(document, "commentRangeStart", id=ident)
            p.insertBefore(
                start,
                next(
                    (
                        child
                        for child in p.childNodes
                        if child.nodeType == Node.ELEMENT_NODE and child.localName != "pPr"
                    ),
                    None,
                ),
            )
            p.appendChild(_word(document, "commentRangeEnd", id=ident))
            run = _word(document, "r")
            run.appendChild(_word(document, "commentReference", id=ident))
            p.appendChild(run)
            comment = _word(comments, "comment", id=ident, author=signer)
            comment.appendChild(_paragraph(comments, item["text"]))
            comments.documentElement.appendChild(comment)
        section = _child(body, "sectPr")
        for line in (
            f"分数　{score}",
            f"总评语　{feedback}",
            f"教师签名　{signer}",
            f"日期　{date}",
        ):
            body.insertBefore(_paragraph(document, line), section)
        replacements = {
            PART: document,
            COMMENTS: comments,
            CONTENT_TYPES: types,
            RELATIONSHIPS: rels,
        }
        for item in original.infolist():
            if item.filename not in replacements:
                result.writestr(item.filename, original.read(item))
        for filename, xml in replacements.items():
            result.writestr(filename, xml.toxml(encoding="utf-8"))
    return output.getvalue()
