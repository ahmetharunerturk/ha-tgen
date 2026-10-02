"""Build the package's camera/clock icon from a small, repo-owned vector design."""

from pathlib import Path

from PIL import Image, ImageDraw

root = Path("custom_components/ha_tgen/brand")
root.mkdir(parents=True, exist_ok=True)
image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((12, 12, 244, 244), radius=56, fill="#326753")
draw.rounded_rectangle((50, 72, 160, 178), radius=18, outline="#ffffff", width=9)
draw.line([(160, 102), (202, 80), (202, 176), (160, 153)], fill="#ffffff", width=9, joint="curve")
draw.ellipse((76, 98, 134, 156), outline="#ffffff", width=6)
draw.line([(105, 108), (105, 128), (116, 136)], fill="#ffffff", width=6, joint="curve")
image.save(root / "icon.png")
image.resize((512, 512), Image.Resampling.LANCZOS).save(root / "icon@2x.png")
(root / "icon.svg").write_text(
    """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="12" y="12" width="232" height="232" rx="56" fill="#326753"/><g fill="none" stroke="white" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"><rect x="50" y="72" width="110" height="106" rx="18"/><path d="m160 102 42-22v96l-42-23"/><circle cx="105" cy="127" r="29" stroke-width="6"/><path d="M105 108v20l11 8" stroke-width="6"/></g></svg>""",
    encoding="utf-8",
)
