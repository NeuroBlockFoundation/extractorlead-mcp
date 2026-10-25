"""Empaqueta la skill para subirla a claude.ai (Settings → Capabilities → Skills).

Uso: python scripts/build_skill_zip.py  →  dist/extractorlead-skill.zip
El zip contiene la carpeta de la skill con SKILL.md en su raíz.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "extractorlead"
OUT = ROOT / "dist" / "extractorlead-skill.zip"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(SKILL.rglob("*")):
            if f.is_file():
                z.write(f, Path(SKILL.name) / f.relative_to(SKILL))
    print(OUT)


if __name__ == "__main__":
    main()
