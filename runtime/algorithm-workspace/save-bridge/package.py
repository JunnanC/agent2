from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata><Identity Language="en-US" Id="edu-save-bridge" Publisher="edu" Version="1.0.0" />
  <DisplayName>Education Workspace Save Bridge</DisplayName><Description xml:space="preserve">Authenticated workspace save status and saveAll bridge.</Description>
  <Tags>workspace</Tags><Categories>Other</Categories><Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.90.0" /></Properties></Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation>
  <Dependencies /><Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" /></Assets>
</PackageManifest>
"""
CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Override PartName="/extension.vsixmanifest" ContentType="text/xml" />
</Types>
"""

with zipfile.ZipFile(sys.argv[1], "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("extension.vsixmanifest", MANIFEST)
    archive.writestr("[Content_Types].xml", CONTENT_TYPES)
    for name in ("package.json", "extension.js"):
        archive.write(ROOT / name, f"extension/{name}")
