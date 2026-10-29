# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[('src/templates', 'templates'), ('src/static', 'static')],
    hiddenimports=['engineio.async_drivers.threading', 'simple_websocket', 'wsproto', 'mcp.server.lowlevel', 'mcp.shared.session', 'mcp.server.models', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='eNSP-MCP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
)
