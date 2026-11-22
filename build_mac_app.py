#!/usr/bin/env python3
# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Compila l'interfaccia nativa usando lo Swift SDK già installato sul Mac."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


def build(output_dir=None, portable=False):
    root = Path(__file__).resolve().parent
    app = (Path(output_dir) if output_dir else root) / 'MainStage Inspector.app'
    contents = app / 'Contents'
    resources = contents / 'Resources'
    executable = contents / 'MacOS' / 'MainStageInspector'
    resources.mkdir(parents=True, exist_ok=True)
    executable.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mainstage-swift-') as cache:
        compiled = Path(cache) / 'MainStageInspector'
        subprocess.run(['swiftc', '-parse-as-library', '-O', '-target', 'arm64-apple-macosx14.0', '-module-cache-path', cache,
                        *[str(source) for source in sorted((root / 'macos').glob('*.swift'))], '-o', str(compiled)], check=True)
        shutil.copy2(compiled, executable)
    for name in ['mainstage_inspector.py', 'plugin_state.py', 'midi_inputs.py', 'concert_features.py']:
        shutil.copy2(root / name, resources / name)
    info = {'CFBundleName': 'MainStage Inspector', 'CFBundleDisplayName': 'MainStage Inspector',
            'CFBundleIdentifier': 'local.mainstage.inspector', 'CFBundleVersion': '13',
            'CFBundleShortVersionString': '1.0.0', 'CFBundleExecutable': 'MainStageInspector',
            'CFBundlePackageType': 'APPL', 'LSMinimumSystemVersion': '14.0',
            'NSHumanReadableCopyright': 'Copyright © 2026 Luantani — GPLv3',
            'NSHighResolutionCapable': True, 'InspectorPython': sys.executable,
            'CFBundleDocumentTypes': [{'CFBundleTypeName': 'MainStage Concert',
                                     'CFBundleTypeExtensions': ['concert'],
                                     'CFBundleTypeRole': 'Viewer', 'LSTypeIsPackage': True}]}
    if portable:
        info.pop('InspectorPython', None)
        info['LSMinimumSystemVersion'] = '15.0'
    shutil.copy2(root / 'LICENSE', resources / 'LICENSE.txt')
    shutil.copy2(root / 'packaging' / 'Informazioni.html', resources / 'Informazioni.html')
    manual = root / 'packaging' / 'Manuale.html'
    if manual.is_file():
        shutil.copy2(manual, resources / 'Manuale.html')
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    print(app)
    return app


if __name__ == '__main__':
    build()
