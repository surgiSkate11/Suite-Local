"""A narrow, typed view of lxml (which ships no type information) for the SRI modules."""

from collections.abc import Iterator, Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, Self, cast


class XmlElement(Protocol):
    tag: str
    text: str | None
    tail: str | None

    def get(self, key: str, default: str | None = None) -> str | None: ...

    def find(self, path: str, namespaces: Mapping[str, str] | None = None) -> Self | None: ...

    def findall(self, path: str, namespaces: Mapping[str, str] | None = None) -> list[Self]: ...

    def iter(self, tag: str | None = None) -> Iterator[Self]: ...

    def remove(self, element: Self) -> None: ...

    def getprevious(self) -> Self | None: ...

    def getparent(self) -> Self | None: ...

    def getroottree(self) -> "XmlTree": ...


class XmlDocInfo(Protocol):
    doctype: str


class XmlTree(Protocol):
    docinfo: XmlDocInfo


class _ErrorEntry(Protocol):
    message: str
    line: int


class _Schema(Protocol):
    error_log: list[_ErrorEntry]

    def validate(self, etree: object) -> bool: ...


class _Etree(Protocol):
    def XMLParser(
        self,
        *,
        resolve_entities: bool,
        no_network: bool,
        load_dtd: bool,
        dtd_validation: bool,
        huge_tree: bool,
    ) -> object: ...

    def fromstring(self, text: bytes, parser: object) -> XmlElement: ...

    def parse(self, source: str) -> object: ...

    def XMLSchema(self, etree: object) -> _Schema: ...

    def tostring(self, element: XmlElement, *, method: str, with_comments: bool) -> bytes: ...


_etree = cast(_Etree, import_module("lxml.etree"))
_NO_ENTITIES = _etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
)


def parse_document(data: bytes) -> XmlElement:
    """Parse untrusted XML: no entities, no DTD, no network. Raises ValueError if malformed."""
    try:
        root = _etree.fromstring(data, _NO_ENTITIES)
    except Exception as error:  # lxml raises XMLSyntaxError, which cannot be named type-safely
        raise ValueError("El XML está mal formado.") from error
    if root.getroottree().docinfo.doctype:
        raise ValueError("El XML no puede declarar un DOCTYPE.")
    return root


def canonicalize(element: XmlElement) -> bytes:
    """Inclusive Canonical XML 1.0 without comments, in the context of its document."""
    return _etree.tostring(element, method="c14n", with_comments=False)


def local_name(element: XmlElement) -> str:
    return element.tag.rpartition("}")[2]


def schema_errors(schema_path: Path, data: bytes) -> list[str]:
    """Messages of every way `data` violates the schema; empty when it is valid."""
    schema = _load_schema(schema_path)
    try:
        document = _etree.fromstring(data, _NO_ENTITIES)
    except Exception as error:
        return [f"XML mal formado: {error}"]
    if schema.validate(document.getroottree()):
        return []
    return [f"línea {entry.line}: {entry.message}" for entry in schema.error_log]


_schemas: dict[Path, _Schema] = {}


def _load_schema(schema_path: Path) -> _Schema:
    if schema_path not in _schemas:
        # Trusted, bundled files: the default parser resolves the entities the W3C schema declares.
        # The schema imports xmldsig-core-schema.xsd by relative path, from the same folder.
        _schemas[schema_path] = _etree.XMLSchema(_etree.parse(str(schema_path)))
    return _schemas[schema_path]
