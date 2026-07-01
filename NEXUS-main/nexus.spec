# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for NEXUS Trading System
Build: pyinstaller nexus.spec
"""
import os
from pathlib import Path

block_cipher = None

ROOT = Path(os.getcwd())

# Collect all backend Python modules
backend_modules = []
backend_dir = ROOT / "backend"
for py_file in backend_dir.rglob("*.py"):
    relative = py_file.relative_to(ROOT)
    module_path = ".".join(relative.with_suffix("").parts)
    backend_modules.append(module_path)

# Hidden imports for packages that PyInstaller may not detect
hidden_imports = [
    "fastapi",
    "uvicorn",
    "uvicorn.lifespan",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.logging",
    "starlette",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.routing",
    "starlette.staticfiles",
    "pydantic",
    "pydantic.fields",
    "pydantic_core",
    "slowapi",
    "slowapi.util",
    "slowapi.errors",
    "numpy",
    "pandas",
    "scipy",
    "ta",
    "httpx",
    "websockets",
    "dotenv",
    "python_dotenv",
    "pythonjsonlogger",
    "pythonjsonlogger.jsonlogger",
    "email.utils",
    "xml.etree.ElementTree",
    "hmac",
    "contextlib",
    "dataclasses",
    "pathlib",
    "logging.config",
    "logging.handlers",
    "asyncio",
    "sqlite3",
    "json",
    "time",
    "uuid",
    "re",
    "collections",
    "math",
    "statistics",
    "typing",
    "typing_extensions",
    "anyio",
    "sniffio",
    "click",
    "h11",
    "httptools",
    "uvloop",
    "watchfiles",
    "wsproto",
    "jinja2",
    "markupsafe",
    "idna",
    "certifi",
    "charset_normalizer",
    "urllib3",
    *backend_modules,
]

# Data files to bundle
datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / ".env"), "."),
    (str(ROOT / ".env.example"), "."),
]

# Include the entire backend source tree
datas.append((str(backend_dir), "backend"))

# Include data directory if it exists
data_dir = ROOT / "data"
if data_dir.exists():
    datas.append((str(data_dir), "data"))

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "pygame",
        "jupyter",
        "IPython",
        "notebook",
        "nbconvert",
        "setuptools",
        "distutils",
        "test",
        "tests",
        "pytest",
        "_pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NEXUS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NEXUS",
)
