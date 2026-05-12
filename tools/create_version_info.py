# -*- coding: utf-8 -*-
import argparse
import re
from pathlib import Path


def read_version(config_path):
    try:
        text = Path(config_path).read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
    except Exception as e:
        print(f"Error reading config: {e}")
    return "0.0.0"

def generate_content(version):
    nums = re.findall(r'\d+', version)
    parts = [int(x) for x in nums]
    while len(parts) < 4:
        parts.append(0)
    ver_tuple = tuple(parts[:4])
    
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'Bomana Team'),
        StringStruct(u'FileDescription', u'Bomana Application'),
        StringStruct(u'FileVersion', u'{version}'),
        StringStruct(u'InternalName', u'Bomana'),
        StringStruct(u'LegalCopyright', u'Copyright (c) 2024 Bomana Team'),
        StringStruct(u'OriginalFilename', u'Bomana.exe'),
        StringStruct(u'ProductName', u'Bomana'),
        StringStruct(u'ProductVersion', u'{version}')])
      ]), 
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    ver = read_version(args.config)
    content = generate_content(ver)
    Path(args.output).write_text(content, encoding="utf-8")
    print(f"Generated version info for v{ver} at {args.output}")
