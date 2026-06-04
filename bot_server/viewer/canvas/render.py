"""SVG renderer for the IR.

Lifted from /home/tan_t/workspace/canvas/canvas/render.py. Only import paths
were rewritten to be relative.
"""
from __future__ import annotations

import html

from .ir import IRState, ROOT_ID
from .layout import CANVAS_H, CANVAS_W, CX, CY

KIND_STYLE: dict[str, dict[str, str]] = {
    "topic":    {"fill": "#fff3cd", "stroke": "#b48a2a", "shape": "round"},
    "decision": {"fill": "#d4edda", "stroke": "#256c3a", "shape": "hex"},
    "action":   {"fill": "#cce5ff", "stroke": "#1d5fa0", "shape": "rect"},
    "question": {"fill": "#f8d7da", "stroke": "#8a2a32", "shape": "round"},
    "fact":     {"fill": "#e8ecef", "stroke": "#4a5057", "shape": "round"},
}

REL_STYLE: dict[str, dict[str, str | None]] = {
    "supports":    {"stroke": "#1f8a3a", "dash": None},
    "contradicts": {"stroke": "#c0392b", "dash": "6,4"},
    "leads_to":    {"stroke": "#1d5fa0", "dash": None},
    "related":     {"stroke": "#888888", "dash": "2,3"},
}


def _wrap_label(label: str, max_chars: int = 10) -> list[str]:
    if len(label) <= max_chars:
        return [label]
    return [label[i : i + max_chars] for i in range(0, len(label), max_chars)]


def render_svg(ir: IRState, root_label: str = "議題") -> str:
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W:.0f} {CANVAS_H:.0f}" '
        'font-family="\'Hiragino Sans\', \'Noto Sans CJK JP\', sans-serif">'
    )
    parts.append('<rect width="100%" height="100%" fill="#fafaf6"/>')

    visible_nodes = ir.visible_nodes()
    vis_ids = {n.id for n in visible_nodes}

    parts.append('<g id="structure" stroke="#c6c4be" stroke-width="2" fill="none">')
    for n in visible_nodes:
        if n.x is None or n.y is None:
            continue
        if n.parent_id == ROOT_ID:
            parts.append(
                f'<line x1="{CX:.1f}" y1="{CY:.1f}" x2="{n.x:.1f}" y2="{n.y:.1f}"/>'
            )
        elif n.parent_id in vis_ids:
            p = ir.nodes[n.parent_id]
            if p.x is not None and p.y is not None:
                parts.append(
                    f'<line x1="{p.x:.1f}" y1="{p.y:.1f}" x2="{n.x:.1f}" y2="{n.y:.1f}"/>'
                )
    parts.append("</g>")

    parts.append('<g id="edges">')
    for e in ir.visible_edges():
        a = ir.nodes[e.from_id]
        b = ir.nodes[e.to_id]
        if a.x is None or b.x is None:
            continue
        style = REL_STYLE.get(e.rel, REL_STYLE["related"])
        dash_attr = (
            f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        )
        parts.append(
            f'<line x1="{a.x:.1f}" y1="{a.y:.1f}" x2="{b.x:.1f}" y2="{b.y:.1f}" '
            f'stroke="{style["stroke"]}" stroke-width="1.5" opacity="0.55"{dash_attr}/>'
        )
    parts.append("</g>")

    parts.append(
        f'<g id="root"><circle cx="{CX:.1f}" cy="{CY:.1f}" r="54" '
        'fill="#fff3cd" stroke="#856404" stroke-width="3"/>'
        f'<text x="{CX:.1f}" y="{CY:.1f}" text-anchor="middle" '
        'dominant-baseline="central" font-size="18" font-weight="bold">'
        f'{html.escape(root_label)}</text></g>'
    )

    parts.append('<g id="nodes">')
    for n in visible_nodes:
        if n.x is None or n.y is None:
            continue
        style = KIND_STYLE.get(n.kind, KIND_STYLE["topic"])
        lines = _wrap_label(n.label)
        max_len = max(len(line) for line in lines)
        w = max(80.0, max_len * 16 + 18)
        h = max(36.0, len(lines) * 22 + 14)
        x = n.x - w / 2
        y = n.y - h / 2
        parts.append(f'<g id="node-{n.id}" class="node kind-{n.kind}">')
        shape = style["shape"]
        if shape == "rect":
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="6" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        elif shape == "hex":
            cx, cy = n.x, n.y
            hw, hh = w / 2, h / 2
            pts = (
                f"{cx-hw:.1f},{cy:.1f} {cx-hw/2:.1f},{cy-hh:.1f} "
                f"{cx+hw/2:.1f},{cy-hh:.1f} {cx+hw:.1f},{cy:.1f} "
                f"{cx+hw/2:.1f},{cy+hh:.1f} {cx-hw/2:.1f},{cy+hh:.1f}"
            )
            parts.append(
                f'<polygon points="{pts}" fill="{style["fill"]}" '
                f'stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="{h/2:.1f}" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        for i, line in enumerate(lines):
            ty = n.y - (len(lines) - 1) * 11 + i * 22
            parts.append(
                f'<text x="{n.x:.1f}" y="{ty:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="14">{html.escape(line)}</text>'
            )
        parts.append('</g>')
    parts.append("</g>")

    legend_y = CANVAS_H - 32
    parts.append('<g id="legend" font-size="12">')
    keys = ["topic", "decision", "action", "question", "fact"]
    labels = {"topic": "議題", "decision": "決定", "action": "TODO", "question": "質問", "fact": "事実"}
    for i, k in enumerate(keys):
        st = KIND_STYLE[k]
        lx = 16 + i * 140
        parts.append(
            f'<rect x="{lx}" y="{legend_y}" width="20" height="14" '
            f'fill="{st["fill"]}" stroke="{st["stroke"]}" stroke-width="1.5"/>'
            f'<text x="{lx+26}" y="{legend_y+11}">{labels[k]}</text>'
        )
    parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts)
