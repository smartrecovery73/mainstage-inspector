#!/usr/bin/env python3
# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Crea un installer Apple Silicon con runtime privato e dipendenze rilocabili."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import platform
import xml.etree.ElementTree as ET

from build_mac_app import build

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.0'
IDENTIFIER = 'local.mainstage.inspector'
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf'}


def run(*args):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True, text=True).stdout


def dependencies(path):
    return sorted(set(re.findall(r'^\t(.+?) \(compatibility version', run('otool', '-L', path), re.M)))


def is_macho(path):
    if not path.is_file() or path.is_symlink():
        return False
    with path.open('rb') as stream:
        return stream.read(4) in MACHO


def bundle_runtime(app):
    resources = app / 'Contents/Resources'
    runtime = resources / 'PythonRuntime'
    framework = Path(sys.base_prefix)
    library = framework / 'Python'
    binary = framework / 'Resources/Python.app/Contents/MacOS/Python'
    if not library.is_file() or not binary.is_file():
        raise RuntimeError('Richiesto un runtime CPython framework di python.org per creare la distribuzione.')
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'lib').mkdir()
    exclusions = {'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo',
                  'ensurepip', 'config-3.13-darwin'}
    def ignore(folder, names):
        return [name for name in names if name in exclusions or name.endswith(('.pyc', '.a'))
                or name.startswith(('_test', '_ctypes_test', 'xx', '_tkinter', '_curses', 'readline'))]
    shutil.copytree(framework / 'lib/python3.13', runtime / 'lib/python3.13', ignore=ignore)
    executable = runtime / 'bin/python3'
    shared = runtime / 'lib/libpython3.13.dylib'
    shutil.copy2(binary, executable)
    shutil.copy2(library, shared)
    sources = {executable: binary, shared: library}
    for path in (runtime / 'lib/python3.13/lib-dynload').glob('*.so'):
        sources[path] = framework / 'lib/python3.13/lib-dynload' / path.name
    mapped = {str(library): shared}
    for target, source in list(sources.items()):
        mapped[str(source)] = target
    visited = set()
    while True:
        pending = [(target, source) for target, source in sources.items() if target not in visited]
        if not pending:
            break
        for target, source in pending:
            visited.add(target)
            for dep in dependencies(source):
                if dep.startswith(('/usr/lib/', '/System/')):
                    continue
                if dep in mapped:
                    continue
                dep_path = Path(dep)
                if not dep.startswith(str(framework) + '/') or not dep_path.is_file():
                    raise RuntimeError(f'Dipendenza non gestita: {source.name}: {dep}')
                destination = runtime / 'lib' / dep_path.name
                shutil.copy2(dep_path, destination)
                mapped[dep] = destination
                sources[destination] = dep_path
    # Include il decoder Zstandard degli stati plugin compressi.
    zstd = Path('/opt/homebrew/lib/libzstd.dylib').resolve()
    if not zstd.is_file():
        raise RuntimeError('libzstd mancante nella macchina di compilazione.')
    native = resources / 'Native/libzstd.dylib'
    native.parent.mkdir()
    shutil.copy2(zstd, native)
    sources[native] = zstd
    for dep in dependencies(zstd):
        if dep != run('otool', '-D', zstd).splitlines()[-1] and not dep.startswith(('/usr/lib/', '/System/')):
            raise RuntimeError(f'Dipendenza zstd non gestita: {dep}')

    def relocate(item):
        target, source = item
        target.chmod(target.stat().st_mode | 0o200)
        architectures = run('lipo', '-archs', target).split()
        if 'arm64' not in architectures:
            raise RuntimeError(f'Binario non Apple Silicon: {target}')
        if len(architectures) > 1:
            thin = target.with_name(target.name + '.thin')
            run('lipo', target, '-thin', 'arm64', '-output', thin)
            thin.replace(target)
        changes = []
        for dep in dependencies(source):
            if dep in mapped:
                relative = os.path.relpath(mapped[dep], target.parent)
                changes += ['-change', dep, '@loader_path/' + relative]
        if target.suffix == '.dylib':
            changes += ['-id', '@rpath/' + target.name]
        if changes:
            run('install_name_tool', *changes, target)
        run('codesign', '--force', '--sign', '-', target)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(relocate, sources.items()))
    licenses = resources / 'Licenses'
    licenses.mkdir()
    shutil.copy2(framework / 'lib/python3.13/LICENSE.txt', licenses / 'Python-LICENSE.txt')
    third_party = framework / 'Resources/English.lproj/Documentation/license.html'
    if not third_party.is_file():
        raise RuntimeError('Licenze terze parti del runtime Python non trovate.')
    shutil.copy2(third_party, licenses / 'Python-ThirdParty-Licenses.html')
    for name in ['LICENSE', 'COPYING']:
        shutil.copy2(zstd.parent.parent / name, licenses / ('Zstandard-' + name + '.txt'))
    (licenses / 'Runtime-info.json').write_text(json.dumps({'python': platform.python_version(), 'zstandard': zstd.name,
                                                          'architecture': 'arm64', 'minimum_macos': '15.0'}, indent=2))
    return runtime


def audit(app):
    resources = app / 'Contents/Resources'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert 'InspectorPython' not in info
    assert not list(app.rglob('*.concert'))
    assert not list(app.rglob('*.cst'))
    assert not list(app.rglob('*.pdf'))
    assert not list(app.rglob('*.pyc'))
    for path in app.rglob('*'):
        if is_macho(path):
            for dep in dependencies(path):
                if not dep.startswith(('/usr/lib/', '/System/', '@loader_path/', '@rpath/')):
                    raise RuntimeError(f'Dipendenza esterna residua: {path.name}: {dep}')
    for path in resources.glob('*.py'):
        if re.search(r'/Users/[^/\s]+', path.read_text()):
            raise RuntimeError(f'Percorso personale in {path.name}')
    run('codesign', '--verify', '--deep', '--strict', app)


def smoke_test(app, concert=None):
    resources = app / 'Contents/Resources'
    runtime = resources / 'PythonRuntime'
    environment = {key: value for key, value in os.environ.items() if not key.startswith('PYTHON') and key != '__PYVENV_LAUNCHER__'}
    environment['PYTHONHOME'] = str(runtime)
    environment['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    command = [str(runtime / 'bin/python3'), '-S', '-B']
    probe = 'import sys,plistlib,zlib,bz2,lzma,ctypes,xml.etree.ElementTree; assert sys.prefix == ' + repr(str(runtime)) + '; print(sys.version)'
    result = subprocess.run(command + ['-c', probe], env=environment, check=True, capture_output=True, text=True)
    print('Runtime privato:', result.stdout.splitlines()[0], flush=True)
    if concert:
        result = subprocess.run(command + [str(resources / 'mainstage_inspector.py'), str(concert), '--json'],
                                env=environment, check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        assert report['name'] == Path(concert).name
        assert report['summary']['strips'] == 0
        print('Analisi del concerto sintetico riuscita.', flush=True)



def main():
    if platform.machine() != 'arm64':
        raise RuntimeError('Questo build produce la versione Apple Silicon e richiede un Mac arm64.')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    package = dist / f'MainStage-Inspector-{VERSION}-AppleSilicon.pkg'
    with tempfile.TemporaryDirectory(prefix='mainstage-package-') as work:
        work = Path(work)
        payload = work / 'payload'
        app = build(payload / 'Applications', portable=True)
        print('Inclusione del runtime e rilocazione delle librerie…', flush=True)
        bundle_runtime(app)
        run('codesign', '--force', '--sign', '-', app)
        audit(app)
        sample = work / 'Example.concert'
        (sample / 'Concert.patch').mkdir(parents=True)
        (sample / 'Concert.patch/data.plist').write_bytes(
            plistlib.dumps({'channels': [], 'patch': {}, 'nodes': []}))
        smoke_test(app, sample)
        component = work / 'MainStageInspector-component.pkg'
        components = work / 'components.plist'
        run('pkgbuild', '--analyze', '--root', payload, components)
        bundle_rules = plistlib.loads(components.read_bytes())
        def disable_relocation(rules):
            for rule in rules:
                rule['BundleIsRelocatable'] = False
                disable_relocation(rule.get('ChildBundles', []))
        disable_relocation(bundle_rules)
        assert any(rule.get('RootRelativeBundlePath') == 'Applications/MainStage Inspector.app'
                   for rule in bundle_rules)
        components.write_bytes(plistlib.dumps(bundle_rules))
        run('pkgbuild', '--root', payload, '--install-location', '/', '--identifier', IDENTIFIER,
            '--version', VERSION, '--ownership', 'recommended', '--component-plist', components, component)
        distribution = work / 'Distribution.xml'
        distribution.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
<title>MainStage Inspector {VERSION}</title>
<options customize="never" require-scripts="false" hostArchitectures="arm64"/>
<domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
<volume-check><allowed-os-versions><os-version min="15.0"/></allowed-os-versions></volume-check>
<readme file="Installazione.html" mime-type="text/html"/>
<choices-outline><line choice="main"/></choices-outline>
<choice id="main" visible="false" title="MainStage Inspector"><pkg-ref id="{IDENTIFIER}"/></choice>
<pkg-ref id="{IDENTIFIER}" version="{VERSION}">MainStageInspector-component.pkg</pkg-ref>
</installer-gui-script>''')
        run('productbuild', '--distribution', distribution, '--resources', ROOT / 'packaging', '--package-path', work, package)
        expanded = work / 'expanded'
        run('pkgutil', '--expand-full', package, expanded)
        installed = list(expanded.rglob('MainStage Inspector.app'))
        assert len(installed) == 1
        package_infos = list(expanded.rglob('PackageInfo'))
        assert len(package_infos) == 1
        package_info = ET.parse(package_infos[0]).getroot()
        assert package_info.get('install-location') == '/'
        assert not package_info.findall('relocate/bundle'), 'Installer potrebbe rilocare l’app esistente'
        assert installed[0].parent.name == 'Applications'
        print('Destinazione verificata: /Applications/MainStage Inspector.app; rilocazione disabilitata.', flush=True)
        print('Verifica dell’app estratta dal pacchetto…', flush=True)
        audit(installed[0])
        smoke_test(installed[0], sample)
        structure = run('xar', '-tf', package)
        assert 'Distribution' in structure
        metadata = ET.parse(expanded / 'Distribution')
        assert metadata.getroot().find('options').get('hostArchitectures') == 'arm64'
    shutil.copy2(ROOT / 'packaging/Manuale.html', dist / 'Manuale-MainStage-Inspector.html')
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    (dist / 'SHA256SUMS.txt').write_text(f'{digest}  {package.name}\n')
    print(f'Pacchetto pronto: {package}\nDimensione: {package.stat().st_size / 1024**2:.1f} MiB\nSHA-256: {digest}', flush=True)


if __name__ == '__main__':
    main()
