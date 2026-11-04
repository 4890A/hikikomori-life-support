"""Prepare the DeepSeek-chan Live2D model for the web viewer.

The model zip ships with Chinese file names, which are awkward in URLs. This copies
the runtime files out of the zip into ``web/public/model/deepseek`` under ASCII names
and writes a matching ``deepseek.model3.json``. The output is gitignored because the
model license forbids redistribution.
"""

import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ZIP = next(ROOT.glob("DeepSeek-chan*.zip"), None)
OUT_DIR = ROOT / "web" / "public" / "model" / "deepseek"

# Bundled motions worth keeping, renamed to ASCII.
MOTIONS = {
    "IDLE.motion3.json": "idle_fx",
    "脱捕.motion3.json": "tracking_lost",
    "竖手指切出来动画.motion3.json": "finger_up",
    "竖手指切回默认.motion3.json": "finger_down",
    "默认手切举手.motion3.json": "hand_chest_on",
    "举手切默认手.motion3.json": "hand_chest_off",
    "狗尾草切换出来.motion3.json": "grass_on",
    "狗尾草切回默认手.motion3.json": "grass_off",
}


def setup_model(zip_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = {PurePosixPath(n): n for n in zf.namelist() if not n.endswith("/")}

        def copy(suffix: str, dest: str) -> None:
            matches = [n for p, n in members.items() if "/DeepSeek/" in n and str(p).endswith(suffix)]
            if len(matches) != 1:
                raise SystemExit(f"expected one match for {suffix!r}, found {matches}")
            target = out_dir / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(matches[0]))
            print(f"  {dest}")

        copy("大肥鱼.moc3", "deepseek.moc3")
        copy("大肥鱼.physics3.json", "deepseek.physics3.json")
        copy("大肥鱼.cdi3.json", "deepseek.cdi3.json")
        textures = []
        for i in range(5):
            name = f"textures/texture_{i:02d}.png"
            copy(f"大肥鱼.4096/texture_{i:02d}.png", name)
            textures.append(name)
        for src, dest in MOTIONS.items():
            copy(f"Animation/{src}", f"motions/{dest}.motion3.json")

    model3 = {
        "Version": 3,
        "FileReferences": {
            "Moc": "deepseek.moc3",
            "Textures": textures,
            "Physics": "deepseek.physics3.json",
            "DisplayInfo": "deepseek.cdi3.json",
        },
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeROpen", "ParamEyeLOpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
        ],
    }
    (out_dir / "deepseek.model3.json").write_text(json.dumps(model3, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'deepseek.model3.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="path to the model zip")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    if args.zip is None or not args.zip.exists():
        raise SystemExit("model zip not found; pass --zip")
    setup_model(args.zip, args.out)
