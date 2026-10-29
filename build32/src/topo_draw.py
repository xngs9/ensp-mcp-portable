# -*- coding: utf-8 -*-
"""
eNSP 拓扑解析与布局：读 .topo / JSON，输出设备/链路数据、自动布局和 Mermaid 文本。

不再生成任何图片（PNG/SVG 均已移除），只服务于拓扑生成、打开和信息查看。
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

TYPE_LABEL = {
    "router": "路由器",
    "switch": "交换机",
    "pc": "PC",
    "firewall": "防火墙",
    "cloud": "云",
    "server": "服务器",
    "generic": "设备",
}


def classify(model: str) -> str:
    """按 eNSP 型号猜设备类型。"""
    m = (model or "").upper().strip()
    if "SERVER" in m:
        return "server"
    if m.startswith("USG") or "FIREWALL" in m or m.startswith("FW"):
        return "firewall"
    if m == "PC" or m.startswith("PC"):
        return "pc"
    if "CLOUD" in m:
        return "cloud"
    if m.startswith(("AR", "NE", "ROUTER")):
        return "router"
    if m.startswith("LSW") or "SWITCH" in m:
        return "switch"
    if m.startswith("S") and any(ch.isdigit() for ch in m):
        return "switch"
    return "generic"


# ---------------------------------------------------------------- 解析

def _read_text(path: str | os.PathLike) -> str:
    """eNSP 的 .topo 声明 encoding="UNICODE"，实际多为 UTF-16 或 UTF-8。"""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="replace")
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_topo(path: str | os.PathLike) -> dict:
    root = ET.fromstring(_read_text(path))
    devices = []
    for d in root.findall(".//devices/dev"):
        settings = d.get("settings") or ""
        ip = ""
        m = re.search(r"-simpc_ip\s+([0-9.]+)", settings)
        if m and m.group(1) != "0.0.0.0":
            ip = m.group(1)
        model = d.get("model") or ""
        devices.append({
            "id": d.get("id") or "",
            "name": d.get("name") or "",
            "model": model,
            "type": classify(model),
            "x": _float(d.get("cx")),
            "y": _float(d.get("cy")),
            "ip": ip,
        })

    ids = {d["id"] for d in devices}
    links = []
    for ln in root.findall(".//lines/line"):
        src, dst = ln.get("srcDeviceID"), ln.get("destDeviceID")
        if src not in ids or dst not in ids:
            continue
        pair = ln.find("interfacePair")
        links.append({
            "src": src,
            "dst": dst,
            "label": (pair.get("lineName") or "") if pair is not None else "",
        })
    return {"title": Path(path).stem, "devices": devices, "links": links}


def normalize_topology(data: dict) -> dict:
    """接受 {devices:[...], links:[...]}，兼容用 name 代替 id 的写法。"""
    devices = []
    by_name = {}
    for i, d in enumerate(data.get("devices") or []):
        model = str(d.get("model") or "")
        dev = {
            "id": str(d.get("id") or d.get("name") or f"dev{i + 1}"),
            "name": str(d.get("name") or d.get("id") or f"设备{i + 1}"),
            "model": model,
            "type": str(d.get("type") or classify(model)),
            "x": _float(d.get("x", 0)),
            "y": _float(d.get("y", 0)),
            "ip": str(d.get("ip") or ""),
        }
        devices.append(dev)
        by_name[dev["name"]] = dev["id"]
        by_name[dev["id"]] = dev["id"]

    links = []
    for l in data.get("links") or []:
        src = by_name.get(str(l.get("src")))
        dst = by_name.get(str(l.get("dst")))
        if src and dst:
            links.append({"src": src, "dst": dst, "label": str(l.get("label") or "")})
    return {"title": str(data.get("title") or "拓扑图"), "devices": devices, "links": links}


# ---------------------------------------------------------------- 自动布局

def auto_layout(topo: dict) -> dict:
    """按连通性分层：路由器/防火墙在第 0 层，之后按 BFS 深度往下排。"""
    devices = topo["devices"]
    if not devices:
        return topo
    ids = {d["id"] for d in devices}
    adj = {i: set() for i in ids}
    for l in topo["links"]:
        adj[l["src"]].add(l["dst"])
        adj[l["dst"]].add(l["src"])

    roots = [d["id"] for d in devices if d["type"] in ("router", "firewall")]
    if not roots:
        roots = sorted(ids, key=lambda i: -len(adj[i]))[:1]

    depth = {}
    q = deque()
    for r in roots:
        depth[r] = 0
        q.append(r)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in depth:
                depth[v] = depth[u] + 1
                q.append(v)
    max_depth = max(depth.values()) if depth else 0
    for i in ids:
        depth.setdefault(i, max_depth + 1)

    layers: dict[int, list] = {}
    by_id = {d["id"]: d for d in devices}
    for i, dep in depth.items():
        layers.setdefault(dep, []).append(by_id[i])

    x_gap, y_gap = 200, 160
    left, top = 110, 110
    max_count = max(len(v) for v in layers.values())
    per_row = 10
    rows_of = {}
    for dep, row in layers.items():
        rows_of[dep] = [row[i:i + per_row] for i in range(0, len(row), per_row)]

    y = top
    for dep in sorted(rows_of):
        for row in rows_of[dep]:
            row = sorted(row, key=lambda d: (d.get("x") or 0, d["name"]))
            n = len(row)
            row_w = (n - 1) * x_gap
            offset = left + (max_count - 1) * x_gap / 2 - row_w / 2
            for i, d in enumerate(row):
                d["x"] = offset + i * x_gap
                d["y"] = y
            y += y_gap
    topo["title"] = topo.get("title") or "拓扑图"
    return topo


def _has_positions(topo: dict) -> bool:
    pts = {(round(d.get("x", 0)), round(d.get("y", 0))) for d in topo["devices"]}
    return len(pts) > 1


def _normalize_positions(topo: dict, margin: int = 100) -> None:
    devices = topo["devices"]
    if not devices:
        return
    min_x = min(d["x"] for d in devices)
    min_y = min(d["y"] for d in devices)
    for d in devices:
        d["x"] = d["x"] - min_x + margin
        d["y"] = d["y"] - min_y + margin


# ---------------------------------------------------------------- Mermaid

def to_mermaid(topo: dict) -> str:
    lines = ["graph TD"]
    ids = {}
    for i, d in enumerate(topo["devices"]):
        nid = f"d{i}"
        ids[d["id"]] = nid
        label = d["name"] or d["id"]
        if d.get("model"):
            label += f"<br/>{d['model']}"
        if d.get("ip"):
            label += f"<br/>{d['ip']}"
        shape = {
            "router": ("((", "))"),
            "switch": ("[", "]"),
            "pc": (">", "]"),
            "cloud": ("((", "))"),
            "server": ("[(", ")]"),
            "firewall": ("{{", "}}"),
        }.get(d["type"], ("[", "]"))
        lines.append(f'    {nid}{shape[0]}"{label}"{shape[1]}')
    for l in topo["links"]:
        a, b = ids.get(l["src"]), ids.get(l["dst"])
        if a and b:
            if l.get("label"):
                lines.append(f'    {a} ---|{l["label"]}| {b}')
            else:
                lines.append(f"    {a} --- {b}")
    return "\n".join(lines)
