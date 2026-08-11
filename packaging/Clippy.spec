from pathlib import Path

project_root = Path(SPECPATH).parent
model_root = project_root / "models" / "all-MiniLM-L6-v2"

a = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(model_root / "model.onnx"), "clippy/resources/models/all-MiniLM-L6-v2"),
        (str(model_root / "tokenizer.json"), "clippy/resources/models/all-MiniLM-L6-v2"),
        (str(project_root / "resources" / "Clippy Logo.png"), "clippy/resources"),
    ],
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "nltk",
        "pandas",
        "pytest",
        "sentence_transformers",
        "tensorflow",
        "tkinter",
        "torch",
        "torchaudio",
        "torchvision",
        "transformers",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Clippy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(project_root / "resources" / "Clippy Logo.png"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
