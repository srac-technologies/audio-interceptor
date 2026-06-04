"""Radial mind-map layout with sticky positions.

Lifted from /home/tan_t/workspace/canvas/canvas/layout.py. Only import paths
were rewritten to be relative.
"""
from __future__ import annotations

import math

from .ir import IRState, Node, ROOT_ID

CANVAS_W = 1400.0
CANVAS_H = 1000.0
CX = CANVAS_W / 2
CY = CANVAS_H / 2

BASE_RADIUS = 210.0
LEVEL_STEP = 150.0
TOP_HALF_WIDTH = math.pi / 8
LEVEL_SHRINK = 0.6


def van_der_corput(k: int) -> float:
    q = 0.0
    bk = 0.5
    while k > 0:
        q += (k & 1) * bk
        k >>= 1
        bk *= 0.5
    return q


def _angle_for_top(child_order: int) -> float:
    return van_der_corput(child_order + 1) * 2 * math.pi - math.pi / 2


def _angle_offset_for_child(child_order: int, half_width: float) -> float:
    return (van_der_corput(child_order + 1) - 0.5) * 2 * half_width


def _depth_of(node_id: str, ir: IRState) -> int:
    if node_id == ROOT_ID:
        return 0
    d = 0
    cur_id = node_id
    while cur_id != ROOT_ID:
        if cur_id not in ir.nodes:
            break
        cur_id = ir.nodes[cur_id].parent_id
        d += 1
        if d > 16:
            break
    return d


def compute_positions(ir: IRState) -> None:
    angles: dict[str, float] = {ROOT_ID: 0.0}
    half_widths: dict[str, float] = {ROOT_ID: math.pi}

    by_parent: dict[str, list[Node]] = {}
    for n in ir.nodes.values():
        by_parent.setdefault(n.parent_id, []).append(n)
    for k in by_parent:
        by_parent[k].sort(key=lambda nd: nd.child_order)

    queue: list[str] = [ROOT_ID]
    while queue:
        pid = queue.pop(0)
        parent_angle = angles.get(pid, 0.0)
        parent_hw = half_widths.get(pid, math.pi)
        parent_depth = _depth_of(pid, ir)
        for n in by_parent.get(pid, []):
            if n.x is None or n.y is None:
                if pid == ROOT_ID:
                    ang = _angle_for_top(n.child_order)
                else:
                    ang = parent_angle + _angle_offset_for_child(
                        n.child_order, parent_hw
                    )
                child_depth = parent_depth + 1
                r = BASE_RADIUS + (child_depth - 1) * LEVEL_STEP
                n.x = CX + r * math.cos(ang)
                n.y = CY + r * math.sin(ang)
            else:
                dx = n.x - CX
                dy = n.y - CY
                ang = math.atan2(dy, dx)
            angles[n.id] = ang
            if pid == ROOT_ID:
                half_widths[n.id] = TOP_HALF_WIDTH
            else:
                half_widths[n.id] = parent_hw * LEVEL_SHRINK
            queue.append(n.id)
