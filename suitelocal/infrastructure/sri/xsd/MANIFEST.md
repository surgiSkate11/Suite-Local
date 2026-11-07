# SRI XSD Schemas — Official Files

These XSD files are the **official schemas** published by the Servicio de Rentas Internas (SRI) of Ecuador for electronic document validation.

**DO NOT modify these files.** If the SRI publishes updated schemas, replace the files and update this manifest.

## Source

Downloaded from: https://www.sri.gob.ec/facturacion-electronica
Section: "Esquemas XSD Y XML"
Date obtained: 2026-04-13

## Files

| File | Document | Version | SHA-256 (line endings normalized to LF) |
|------|----------|---------|------|
| `factura_V1.1.0.xsd` | Factura | 1.1.0 | `62db9bf0ecceb00ef2b7ed136e59224815e5e5e33c77efc6a0552001e052eb8b` |
| `xmldsig-core-schema.xsd` | W3C XML Signature schema, imported by the factura schema | 2002 | `35cf8197da812c85e40d57891b35c94187569ed474a2dac813ce5090dafcd35c` |

The factura hash is the one the SRI MANIFEST published (36,356 bytes with LF endings); it was
verified here after normalizing CRLF. The upstream MANIFEST did not list `xmldsig-core-schema.xsd`,
so its hash is recorded by this project and checked by the tests to detect accidental edits.

Only the factura schema (and the W3C schema it imports) is used: SuiteLocal issues invoices only.
The other SRI schemas (liquidación de compra, notas de crédito/débito, guía de remisión,
retención) are not included.

## Reference

The XSD files are loaded from disk by `suitelocal/infrastructure/sri/invoice_xml.py`
(`validate_against_xsd`). The relative `schemaLocation` of the import requires both files to stay
in this directory.
