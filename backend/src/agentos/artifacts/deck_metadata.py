"""Standard OOXML custom properties: provenance never changes authored notes."""

import json
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


def stamp(data: bytes, manifest: dict) -> bytes:
    props_ns = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    vt_ns = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    props = ET.Element(f"{{{props_ns}}}Properties")
    entry = ET.SubElement(
        props,
        f"{{{props_ns}}}property",
        {
            "fmtid": "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            "pid": "2",
            "name": "CaberOSExportManifest",
        },
    )
    ET.SubElement(entry, f"{{{vt_ns}}}lpwstr").text = json.dumps(manifest, ensure_ascii=False)
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        types = ET.fromstring(source.read("[Content_Types].xml"))
        ET.SubElement(
            types,
            f"{{{types_ns}}}Override",
            {
                "PartName": "/docProps/custom.xml",
                "ContentType": (
                    "application/vnd.openxmlformats-officedocument.custom-properties+xml"
                ),
            },
        )
        rels = ET.fromstring(source.read("_rels/.rels"))
        ET.SubElement(
            rels,
            f"{{{rel_ns}}}Relationship",
            {
                "Id": "rIdCaberOSManifest",
                "Target": "docProps/custom.xml",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties",
            },
        )
        for name in source.namelist():
            if name not in {"[Content_Types].xml", "_rels/.rels", "docProps/custom.xml"}:
                target.writestr(name, source.read(name))
        target.writestr(
            "[Content_Types].xml", ET.tostring(types, encoding="utf-8", xml_declaration=True)
        )
        target.writestr("_rels/.rels", ET.tostring(rels, encoding="utf-8", xml_declaration=True))
        target.writestr(
            "docProps/custom.xml", ET.tostring(props, encoding="utf-8", xml_declaration=True)
        )
    return output.getvalue()
