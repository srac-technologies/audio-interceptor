"""Intermediate representation for the graphic recording.

Lifted verbatim from /home/tan_t/workspace/canvas/canvas/ir.py (same author);
no logic changes here. See that project's commit history for evolution.

Design goals:
- Stable IDs from canonical labels (immune to whitespace/punctuation drift).
- Append-only by default (nodes are added or updated, never structurally moved).
- Lenient ingestion: tolerate different field names the LLM may use.
- Visibility gate (mention threshold) usable for debouncing flicker.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

NodeKind = Literal["topic", "decision", "action", "question", "fact"]
EdgeRel = Literal["supports", "contradicts", "leads_to", "related"]

ROOT_ID = "root"
VALID_KINDS: set[str] = {"topic", "decision", "action", "question", "fact"}
VALID_RELS: set[str] = {"supports", "contradicts", "leads_to", "related"}


def normalize_label(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[、。,.!?！？「」『』()（）\[\]【】・:：;；\-—–]", "", s)
    return s.lower()


def stable_id(label: str) -> str:
    canon = normalize_label(label)
    return "n" + hashlib.blake2b(canon.encode("utf-8"), digest_size=5).hexdigest()


@dataclass
class Node:
    id: str
    label: str
    kind: str
    parent_id: str
    state: Literal["pending", "visible"] = "pending"
    mention_count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    child_order: int = 0
    x: Optional[float] = None
    y: Optional[float] = None


@dataclass
class Edge:
    from_id: str
    to_id: str
    rel: str


class IRState:
    def __init__(self, visible_threshold: int = 1) -> None:
        self.visible_threshold = visible_threshold
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        self._child_count: dict[str, int] = {}

    def _resolve_parent(self, parent_ref: str) -> str:
        if not parent_ref:
            return ROOT_ID
        p = parent_ref.strip()
        if p.lower() == "root" or p == "根" or p == "ルート":
            return ROOT_ID
        target_id = stable_id(p)
        if target_id in self.nodes:
            return target_id
        target_norm = normalize_label(p)
        if not target_norm:
            return ROOT_ID
        for n in self.nodes.values():
            cand = normalize_label(n.label)
            if cand == target_norm:
                return n.id
        for n in self.nodes.values():
            cand = normalize_label(n.label)
            if target_norm in cand or cand in target_norm:
                return n.id
        return ROOT_ID

    def add_or_update_node(
        self, label: str, kind: str, parent_ref: str
    ) -> tuple[Node, bool]:
        nid = stable_id(label)
        if nid in self.nodes:
            n = self.nodes[nid]
            n.mention_count += 1
            n.last_seen = time.time()
            if n.mention_count >= self.visible_threshold:
                n.state = "visible"
            return n, False
        parent_id = self._resolve_parent(parent_ref)
        if parent_id == nid:
            parent_id = ROOT_ID
        order = self._child_count.get(parent_id, 0)
        self._child_count[parent_id] = order + 1
        n = Node(
            id=nid,
            label=label.strip(),
            kind=kind if kind in VALID_KINDS else "topic",
            parent_id=parent_id,
            child_order=order,
        )
        if self.visible_threshold <= 1:
            n.state = "visible"
        self.nodes[nid] = n
        return n, True

    def add_edge(self, from_label: str, to_label: str, rel: str) -> Optional[Edge]:
        fid = stable_id(from_label)
        tid = stable_id(to_label)
        if fid not in self.nodes or tid not in self.nodes:
            return None
        if fid == tid:
            return None
        rel_norm = rel if rel in VALID_RELS else "related"
        key = (fid, tid, rel_norm)
        if key in self._edge_keys:
            return None
        self._edge_keys.add(key)
        e = Edge(fid, tid, rel_norm)
        self.edges.append(e)
        return e

    def visible_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.state == "visible"]

    def visible_edges(self) -> list[Edge]:
        vis = {n.id for n in self.visible_nodes()}
        return [e for e in self.edges if e.from_id in vis and e.to_id in vis]

    def summary(self, max_chars: int = 1200) -> str:
        lines: list[str] = []
        for n in self.nodes.values():
            parent_label = ""
            if n.parent_id != ROOT_ID and n.parent_id in self.nodes:
                parent_label = self.nodes[n.parent_id].label
            else:
                parent_label = "root"
            lines.append(f"- [{n.kind}] {n.label} (親: {parent_label})")
        out = "\n".join(lines)
        if len(out) > max_chars:
            out = out[-max_chars:]
        return out


def apply_llm_result(ir: IRState, llm_out: dict[str, Any]) -> dict[str, int]:
    stats = {"nodes_new": 0, "nodes_seen": 0, "edges_new": 0, "edges_dup": 0}
    node_list = (
        llm_out.get("nodes")
        or llm_out.get("add_nodes")
        or llm_out.get("update_nodes")
        or []
    )
    if isinstance(node_list, dict):
        node_list = list(node_list.values())
    for n in node_list:
        if not isinstance(n, dict):
            continue
        label = (
            n.get("label")
            or n.get("text")
            or n.get("title")
            or n.get("name")
            or ""
        )
        if not isinstance(label, str) or not label.strip():
            continue
        kind = n.get("kind") or n.get("type") or n.get("category") or "topic"
        parent = (
            n.get("parent_label")
            or n.get("parent")
            or n.get("parent_id")
            or "root"
        )
        _, created = ir.add_or_update_node(label, str(kind), str(parent))
        if created:
            stats["nodes_new"] += 1
        else:
            stats["nodes_seen"] += 1

    edge_list = (
        llm_out.get("edges")
        or llm_out.get("add_edges")
        or llm_out.get("links")
        or []
    )
    if isinstance(edge_list, dict):
        edge_list = list(edge_list.values())
    for e in edge_list:
        if not isinstance(e, dict):
            continue
        fl = e.get("from_label") or e.get("source") or e.get("from") or ""
        tl = e.get("to_label") or e.get("target") or e.get("to") or ""
        rel = (
            e.get("rel")
            or e.get("relation")
            or e.get("label")
            or e.get("type")
            or "related"
        )
        if not fl or not tl:
            continue
        added = ir.add_edge(str(fl), str(tl), str(rel))
        if added is not None:
            stats["edges_new"] += 1
        else:
            stats["edges_dup"] += 1

    return stats
