"""Render a DXF drawing to PNG (for the UI and for vision-model questions)."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import ezdxf  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402


def render_png(dxf_path: str | Path, dpi: int = 150, size_in: float = 10.0) -> bytes:
    """Return the drawing's modelspace as PNG bytes on a white background."""
    doc = ezdxf.readfile(str(dxf_path))
    fig = plt.figure(figsize=(size_in, size_in * 0.75))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    ctx.set_current_layout(doc.modelspace())
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                        color_policy=ColorPolicy.COLOR)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def cached_png(dxf_path: str | Path, cache_dir: str | Path, dpi: int = 150, size_in: float = 10.0) -> bytes:
    """render_png takes 2-3 s per drawing, so keep each result on disk, keyed by file content and settings."""
    p = Path(dxf_path)
    digest = hashlib.md5(p.read_bytes()).hexdigest()[:10]
    out = Path(cache_dir) / f"{p.stem}-{digest}-{dpi}-{size_in:g}.png"
    if out.is_file():
        return out.read_bytes()
    data = render_png(p, dpi=dpi, size_in=size_in)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    except OSError:  # read-only disk: still return the render
        pass
    return data


def save_png(dxf_path: str | Path, out_path: str | Path, dpi: int = 150) -> Path:
    Path(out_path).write_bytes(render_png(dxf_path, dpi=dpi))
    return Path(out_path)
