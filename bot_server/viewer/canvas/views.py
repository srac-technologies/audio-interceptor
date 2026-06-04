"""Multiple view renderers over the same IR.

Lifted from /home/tan_t/workspace/canvas/canvas/views.py. Only import paths
were rewritten to be relative.

Each renderer returns {"view_type": "svg|html|mermaid", "content": "..."}.
"""
from __future__ import annotations

import html
import time
from typing import Any

from .ir import IRState, ROOT_ID
from .layout import compute_positions, van_der_corput
from .render import KIND_STYLE, REL_STYLE, _wrap_label, render_svg

VIEW_MODES = ("mindmap", "tree", "kanban", "mermaid", "transcript")
DEFAULT_VIEW = "mindmap"


def _group_by_parent(ir: IRState) -> dict[str, list]:
    by_parent: dict[str, list] = {}
    for n in ir.nodes.values():
        by_parent.setdefault(n.parent_id, []).append(n)
    for k in by_parent:
        by_parent[k].sort(key=lambda x: x.child_order)
    return by_parent


def render_mindmap(ir: IRState) -> dict[str, str]:
    compute_positions(ir)
    return {"view_type": "svg", "content": render_svg(ir)}


TREE_W = 1500.0
TREE_H = 950.0
TREE_LEVEL_X = 280.0
TREE_BASE_X = 80.0
TREE_BAND_TOP = 780.0
TREE_BAND_SHRINK = 0.55


def render_tree(ir: IRState) -> dict[str, str]:
    positions: dict[str, tuple[float, float]] = {ROOT_ID: (TREE_BASE_X, TREE_H / 2)}
    bands: dict[str, float] = {ROOT_ID: TREE_BAND_TOP}
    by_parent = _group_by_parent(ir)

    queue: list[str] = [ROOT_ID]
    while queue:
        pid = queue.pop(0)
        px, py = positions[pid]
        band = bands[pid]
        children = by_parent.get(pid, [])
        for n in children:
            if n.state != "visible":
                continue
            x = px + TREE_LEVEL_X
            y = py + (van_der_corput(n.child_order + 1) - 0.5) * band
            positions[n.id] = (x, y)
            bands[n.id] = band * TREE_BAND_SHRINK
            queue.append(n.id)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {TREE_W:.0f} {TREE_H:.0f}" '
        'font-family="\'Hiragino Sans\', \'Noto Sans CJK JP\', sans-serif">'
    )
    parts.append('<rect width="100%" height="100%" fill="#fafaf6"/>')

    visible = [n for n in ir.nodes.values() if n.state == "visible" and n.id in positions]

    parts.append('<g id="structure" stroke="#c6c4be" stroke-width="2" fill="none">')
    for n in visible:
        nx, ny = positions[n.id]
        if n.parent_id == ROOT_ID:
            px, py = positions[ROOT_ID]
        elif n.parent_id in positions:
            px, py = positions[n.parent_id]
        else:
            continue
        mid_x = (px + nx) / 2
        parts.append(
            f'<path d="M{px:.1f},{py:.1f} L{mid_x:.1f},{py:.1f} '
            f'L{mid_x:.1f},{ny:.1f} L{nx:.1f},{ny:.1f}"/>'
        )
    parts.append("</g>")

    parts.append('<g id="edges">')
    for e in ir.visible_edges():
        if e.from_id not in positions or e.to_id not in positions:
            continue
        ax, ay = positions[e.from_id]
        bx, by = positions[e.to_id]
        style = REL_STYLE.get(e.rel, REL_STYLE["related"])
        dash = f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        parts.append(
            f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{style["stroke"]}" stroke-width="1.5" opacity="0.5"{dash}/>'
        )
    parts.append("</g>")

    rx, ry = positions[ROOT_ID]
    parts.append(
        f'<g id="root"><rect x="{rx-50:.1f}" y="{ry-26:.1f}" width="100" height="52" rx="6" '
        f'fill="#fff3cd" stroke="#856404" stroke-width="3"/>'
        f'<text x="{rx:.1f}" y="{ry:.1f}" text-anchor="middle" dominant-baseline="central" '
        f'font-size="16" font-weight="bold">議題</text></g>'
    )

    parts.append('<g id="nodes">')
    for n in visible:
        nx, ny = positions[n.id]
        style = KIND_STYLE.get(n.kind, KIND_STYLE["topic"])
        lines = _wrap_label(n.label, max_chars=10)
        max_len = max(len(l) for l in lines)
        w = max(120.0, max_len * 16 + 18)
        h = max(36.0, len(lines) * 22 + 14)
        parts.append(f'<g id="node-{n.id}" class="node kind-{n.kind}">')
        if style["shape"] == "rect":
            parts.append(
                f'<rect x="{nx-w/2:.1f}" y="{ny-h/2:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="6" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        elif style["shape"] == "hex":
            hw, hh = w / 2, h / 2
            pts = (
                f"{nx-hw:.1f},{ny:.1f} {nx-hw/2:.1f},{ny-hh:.1f} "
                f"{nx+hw/2:.1f},{ny-hh:.1f} {nx+hw:.1f},{ny:.1f} "
                f"{nx+hw/2:.1f},{ny+hh:.1f} {nx-hw/2:.1f},{ny+hh:.1f}"
            )
            parts.append(
                f'<polygon points="{pts}" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<rect x="{nx-w/2:.1f}" y="{ny-h/2:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="{h/2:.1f}" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="2"/>'
            )
        for i, line in enumerate(lines):
            ty = ny - (len(lines) - 1) * 11 + i * 22
            parts.append(
                f'<text x="{nx:.1f}" y="{ty:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="14">{html.escape(line)}</text>'
            )
        parts.append("</g>")
    parts.append("</g>")
    parts.append("</svg>")
    return {"view_type": "svg", "content": "\n".join(parts)}


KANBAN_W = 1500.0
KANBAN_H = 950.0
KANBAN_COLS = ("topic", "decision", "action", "question", "fact")
KANBAN_COL_TITLES = {
    "topic": "議題", "decision": "決定", "action": "TODO",
    "question": "質問", "fact": "事実",
}


def render_kanban(ir: IRState) -> dict[str, str]:
    col_w = KANBAN_W / len(KANBAN_COLS)
    card_pad = 10.0
    card_min_h = 56.0
    top_y = 60.0
    inner_w = col_w - 28

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {KANBAN_W:.0f} {KANBAN_H:.0f}" '
        'font-family="\'Hiragino Sans\', \'Noto Sans CJK JP\', sans-serif">'
    )
    parts.append('<rect width="100%" height="100%" fill="#fafaf6"/>')

    parts.append('<g id="columns">')
    for i, kind in enumerate(KANBAN_COLS):
        cx = i * col_w
        style = KIND_STYLE[kind]
        parts.append(
            f'<rect x="{cx+6:.1f}" y="14" width="{col_w-12:.1f}" height="34" rx="6" '
            f'fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.5"/>'
            f'<text x="{cx+col_w/2:.1f}" y="36" text-anchor="middle" font-size="16" '
            f'font-weight="bold" fill="#333">{KANBAN_COL_TITLES[kind]}</text>'
        )
        if i > 0:
            parts.append(
                f'<line x1="{cx:.1f}" y1="58" x2="{cx:.1f}" y2="{KANBAN_H-10:.1f}" '
                'stroke="#dcd9d2" stroke-width="1"/>'
            )
    parts.append("</g>")

    parts.append('<g id="nodes">')
    for i, kind in enumerate(KANBAN_COLS):
        cx = i * col_w
        kind_nodes = sorted(
            [n for n in ir.visible_nodes() if n.kind == kind],
            key=lambda n: n.first_seen,
        )
        cur_y = top_y
        for n in kind_nodes:
            lines = _wrap_label(n.label, max_chars=max(6, int(inner_w / 18)))
            h = max(card_min_h, 14 + len(lines) * 22)
            style = KIND_STYLE[kind]
            parts.append(f'<g id="node-{n.id}" class="node kind-{n.kind}">')
            parts.append(
                f'<rect x="{cx+14:.1f}" y="{cur_y:.1f}" width="{inner_w:.1f}" height="{h:.1f}" '
                f'rx="6" fill="white" stroke="{style["stroke"]}" stroke-width="1.5"/>'
            )
            parts.append(
                f'<rect x="{cx+14:.1f}" y="{cur_y:.1f}" width="6" height="{h:.1f}" '
                f'rx="3" fill="{style["stroke"]}"/>'
            )
            for li, line in enumerate(lines):
                ty = cur_y + 14 + li * 22
                parts.append(
                    f'<text x="{cx+30:.1f}" y="{ty:.1f}" dominant-baseline="hanging" '
                    f'font-size="14" fill="#222">{html.escape(line)}</text>'
                )
            parts.append("</g>")
            cur_y += h + card_pad

    parts.append("</g>")
    parts.append("</svg>")
    return {"view_type": "svg", "content": "\n".join(parts)}


def _mermaid_safe(label: str) -> str:
    s = label
    table = str.maketrans(
        {"(": "（", ")": "）", "[": "［", "]": "］",
         "{": "｛", "}": "｝", "\"": "'", "\n": " "}
    )
    s = s.translate(table)
    return s.strip() or "?"


def render_mermaid(ir: IRState) -> dict[str, str]:
    by_parent = _group_by_parent(ir)
    lines = ["mindmap", "  root((議題))"]

    def walk(pid: str, depth: int) -> None:
        for n in by_parent.get(pid, []):
            if n.state != "visible":
                continue
            indent = "  " * (depth + 2)
            label = _mermaid_safe(n.label)
            if n.kind == "decision":
                token = f"{{{{{label}}}}}"
            elif n.kind == "action":
                token = f"[{label}]"
            elif n.kind == "question":
                token = f"({label}?)"
            else:
                token = f"({label})"
            lines.append(f"{indent}{token}")
            walk(n.id, depth + 1)

    walk(ROOT_ID, 0)
    return {"view_type": "mermaid", "content": "\n".join(lines)}


def render_transcript(chunks_log: list[dict[str, Any]]) -> dict[str, str]:
    if not chunks_log:
        body = '<div class="empty">議事録はまだありません。</div>'
        return {"view_type": "html", "content": body}
    parts: list[str] = ['<div class="transcript">']
    for entry in chunks_log:
        ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
        text = html.escape(entry["text"])
        stats = entry.get("stats") or {}
        lat = entry.get("latency", 0.0)
        meta = (
            f'+{stats.get("nodes_new", 0)}node / '
            f'+{stats.get("edges_new", 0)}edge / '
            f'{lat:.1f}s'
        )
        parts.append(
            '<div class="entry">'
            f'<div class="head"><span class="ts">{ts}</span>'
            f'<span class="meta">{meta}</span></div>'
            f'<div class="text">{text}</div>'
            "</div>"
        )
    parts.append("</div>")
    return {"view_type": "html", "content": "\n".join(parts)}


def render_view(
    ir: IRState, chunks_log: list[dict[str, Any]], mode: str
) -> dict[str, str]:
    if mode == "tree":
        return render_tree(ir)
    if mode == "kanban":
        return render_kanban(ir)
    if mode == "mermaid":
        return render_mermaid(ir)
    if mode == "transcript":
        return render_transcript(chunks_log)
    return render_mindmap(ir)
