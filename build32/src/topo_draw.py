# -*- coding: utf-8 -*-
"""
eNSP 拓扑自动绘图：解析 .topo / JSON，自动布局，输出 SVG / Mermaid。

不依赖 eNSP 运行，也不下发任何配置，只负责把设备与连线画成图。

命令行示例：
    python topo_draw.py C:\\Users\\30582\\Desktop\\1\\1.topo -o 1.svg
    python topo_draw.py 1.topo -o 1.svg --layout auto
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

# ---------------------------------------------------------------- 设备类型

TYPE_STYLE = {
    "router":   {"fill": "#dbeafe", "stroke": "#2563eb", "label": "路由器"},
    "switch":   {"fill": "#dcfce7", "stroke": "#16a34a", "label": "交换机"},
    "pc":       {"fill": "#f1f5f9", "stroke": "#475569", "label": "PC"},
    "firewall": {"fill": "#fee2e2", "stroke": "#dc2626", "label": "防火墙"},
    "cloud":    {"fill": "#f3e8ff", "stroke": "#9333ea", "label": "云"},
    "server":   {"fill": "#fef3c7", "stroke": "#d97706", "label": "服务器"},
    "generic":  {"fill": "#e2e8f0", "stroke": "#334155", "label": "设备"},
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
    """eNSP 的 .topo 声明 encoding="UNICODE"，实际多为 UTF-16，做兼容读取。"""
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
    # 去掉 XML 声明里的非标准 encoding，交给 ElementTree 直接吃字符串
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)


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


def _float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


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

    # 每层最多 10 个一行，超过就换行
    per_row = 10
    rows_of = {}
    for dep, row in layers.items():
        rows_of[dep] = [row[i:i + per_row] for i in range(0, len(row), per_row)]

    total_rows = sum(len(v) for v in rows_of.values())
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


# ---------------------------------------------------------------- SVG 渲染

def _icon(kind: str, stroke: str, fill: str) -> str:
    s = f'stroke="{stroke}" stroke-width="2" fill="{fill}" stroke-linejoin="round"'
    if kind == "router":
        return (
            f'<circle cx="0" cy="0" r="26" {s}/>'
            f'<path d="M-15 -8 L15 -8 M9 -14 L15 -8 L9 -2" fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M15 8 L-15 8 M-9 2 L-15 8 L-9 14" fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round"/>'
        )
    if kind == "switch":
        ports = "".join(
            f'<rect x="{-20 + i * 8}" y="8" width="5" height="6" rx="1" fill="{stroke}"/>'
            for i in range(6)
        )
        return (
            f'<rect x="-30" y="-22" width="60" height="44" rx="6" {s}/>'
            f'<path d="M-16 -8 L16 -8 M10 -13 L16 -8 L10 -3" fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M16 0 L-16 0 M-10 -5 L-16 0 L-10 5" fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round"/>'
            + ports
        )
    if kind == "pc":
        return (
            f'<rect x="-26" y="-26" width="52" height="36" rx="3" {s}/>'
            f'<rect x="-21" y="-21" width="42" height="26" rx="1" fill="#ffffff" stroke="{stroke}" stroke-width="1.5"/>'
            f'<path d="M0 10 L0 20 M-12 22 L12 22" fill="none" stroke="{stroke}" stroke-width="2.5" stroke-linecap="round"/>'
        )
    if kind == "firewall":
        bricks = "".join(
            f'<path d="M-26 {y} L26 {y}" stroke="{stroke}" stroke-width="1.2"/>'
            for y in (-14, -2, 10)
        )
        return (
            f'<rect x="-28" y="-24" width="56" height="48" rx="4" {s}/>'
            + bricks
            + f'<path d="M-10 -24 L-10 24 M10 -24 L10 24" stroke="{stroke}" stroke-width="1.2"/>'
        )
    if kind == "cloud":
        return (
            f'<path d="M-30 8 C-40 8 -40 -8 -28 -10 C-26 -24 -6 -28 2 -18 '
            f'C8 -30 28 -26 28 -12 C40 -10 40 8 28 8 Z" {s}/>'
        )
    if kind == "server":
        slots = "".join(
            f'<rect x="-22" y="{-20 + i * 12}" width="44" height="8" rx="2" fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/>'
            for i in range(4)
        )
        return f'<rect x="-28" y="-26" width="56" height="52" rx="4" {s}/>' + slots
    return f'<rect x="-28" y="-24" width="56" height="48" rx="8" {s}/>'


def prepare(topo: dict, layout: str = "keep") -> tuple:
    """统一坐标与画布范围，SVG 共用。"""
    if layout == "auto" or not _has_positions(topo):
        auto_layout(topo)
    else:
        _normalize_positions(topo)

    devices = topo["devices"]
    links = topo["links"]
    xs = [d["x"] for d in devices] or [0]
    ys = [d["y"] for d in devices] or [0]
    min_x, max_x = min(xs) - 90, max(xs) + 90
    min_y, max_y = min(ys) - 80, max(ys) + 200
    width = max(640, int(max_x - min_x))
    height = max(420, int(max_y - min_y))
    return devices, links, min_x, min_y, width, height


def render_svg(topo: dict, show_ip: bool = True, show_link_labels: bool = False,
               title: str | None = None, layout: str = "keep") -> tuple[str, int, int]:
    devices, links, min_x, min_y, width, height = prepare(topo, layout)
    by_id = {d["id"]: d for d in devices}
    canvas_title = title or topo.get("title") or ""
    if not canvas_title or canvas_title.isdigit():
        canvas_title = "eNSP 网络拓扑图"
    vb = f"{int(min_x)} {int(min_y)} {width} {height}"

    # 平行连线错开
    pair_count: dict[tuple, int] = {}
    for l in links:
        key = tuple(sorted((l["src"], l["dst"])))
        pair_count[key] = pair_count.get(key, 0) + 1
    pair_seen: dict[tuple, int] = {}

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="{vb}" font-family="Microsoft YaHei, Segoe UI, Arial, sans-serif">'
    )
    parts.append(f'<rect x="{min_x}" y="{min_y}" width="{width}" height="{height}" fill="#ffffff"/>')
    parts.append(
        f'<text x="{min_x + width / 2}" y="{min_y + 40}" text-anchor="middle" '
        f'font-size="22" font-weight="700" fill="#0f172a">{html.escape(canvas_title)}</text>'
    )

    # 连线
    for l in links:
        a, b = by_id.get(l["src"]), by_id.get(l["dst"])
        if not a or not b:
            continue
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        dist = math.hypot(dx, dy) or 1
        ux, uy = dx / dist, dy / dist
        key = tuple(sorted((l["src"], l["dst"])))
        idx = pair_seen.get(key, 0)
        pair_seen[key] = idx + 1
        if pair_count[key] > 1:
            off = (idx - (pair_count[key] - 1) / 2) * 12
            ux, uy = ux + -uy * off / dist, uy + ux * off / dist
        r = 40
        x1, y1 = a["x"] + ux * r, a["y"] + uy * r
        x2, y2 = b["x"] - ux * r, b["y"] - uy * r
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#94a3b8" stroke-width="2.5" stroke-linecap="round"/>'
        )
        label = (l.get("label") or "").strip()
        if show_link_labels and label and label.lower() != "copper":
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            parts.append(
                f'<text x="{mx:.1f}" y="{my - 6:.1f}" text-anchor="middle" font-size="11" '
                f'fill="#475569" paint-order="stroke" stroke="#ffffff" stroke-width="3">'
                f'{html.escape(label)}</text>'
            )

    # 设备
    for d in devices:
        style = TYPE_STYLE.get(d["type"], TYPE_STYLE["generic"])
        name = html.escape(d["name"] or d["id"])
        model = html.escape(d["model"] or "")
        parts.append(f'<g transform="translate({d["x"]:.1f},{d["y"]:.1f})">')
        parts.append(_icon(d["type"], style["stroke"], style["fill"]))
        parts.append(
            f'<text y="52" text-anchor="middle" font-size="14" font-weight="700" '
            f'fill="#0f172a">{name}</text>'
        )
        if model:
            parts.append(
                f'<text y="69" text-anchor="middle" font-size="11" fill="#64748b">{model}</text>'
            )
        if show_ip and d.get("ip"):
            parts.append(
                f'<text y="85" text-anchor="middle" font-size="11" fill="#2563eb">{html.escape(d["ip"])}</text>'
            )
        parts.append("</g>")

    # 图例：底部横向排列，超出宽度自动换行
    used = sorted({d["type"] for d in devices})
    slot = 118
    per_row = max(1, int((width - 48) // slot))
    rows = [used[i:i + per_row] for i in range(0, len(used), per_row)] or [[]]
    y0 = min_y + height - 30 - (len(rows) - 1) * 24
    parts.append(
        f'<text x="{min_x + 24}" y="{y0 - 18}" font-size="12" font-weight="700" fill="#334155">图例</text>'
    )
    for r, row in enumerate(rows):
        yy = y0 + r * 24
        for i, t in enumerate(row):
            st = TYPE_STYLE.get(t, TYPE_STYLE["generic"])
            xx = min_x + 24 + i * slot
            parts.append(
                f'<rect x="{xx}" y="{yy - 10}" width="14" height="14" rx="3" '
                f'fill="{st["fill"]}" stroke="{st["stroke"]}" stroke-width="1.5"/>'
            )
            count = sum(1 for d in devices if d["type"] == t)
            parts.append(
                f'<text x="{xx + 22}" y="{yy + 1}" font-size="12" fill="#334155">'
                f'{html.escape(st["label"])} ({count})</text>'
            )

    parts.append(
        f'<text x="{min_x + width - 24}" y="{min_y + 40}" text-anchor="end" font-size="11" '
        f'fill="#94a3b8">设备 {len(devices)} 台 · 链路 {len(links)} 条</text>'
    )
    parts.append("</svg>")
    return "".join(parts), width, height


# ---------------------------------------------------------------- 导出

def save_svg(svg: str, out_path: str | os.PathLike) -> str:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return str(out)


def render_to_file(topo: dict, output: str, layout: str = "keep",
                   show_ip: bool = True, show_link_labels: bool = False,
                   title: str | None = None) -> dict:
    out = Path(output)
    fmt = out.suffix.lower().lstrip(".")
    if fmt not in ("", "svg"):
        raise ValueError("只支持 .svg 输出（PNG 导出已移除）")
    svg, width, height = render_svg(topo, show_ip=show_ip,
                                    show_link_labels=show_link_labels,
                                    title=title, layout=layout)
    final = save_svg(svg, out)
    return {
        "output": final,
        "format": fmt or "svg",
        "width": width,
        "height": height,
        "devices": len(topo["devices"]),
        "links": len(topo["links"]),
    }


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


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="把 eNSP .topo 自动画成 SVG")
    ap.add_argument("input", help=".topo 文件或 .json 文件")
    ap.add_argument("-o", "--output", help="输出 SVG 文件（.svg）")
    ap.add_argument("--layout", choices=["keep", "auto"], default="keep",
                    help="keep 用 .topo 里的原坐标，auto 重新分层布局")
    ap.add_argument("--no-ip", action="store_true", help="不显示 PC/服务器 IP")
    ap.add_argument("--link-labels", action="store_true", help="显示连线标签")
    ap.add_argument("--title", help="图标题")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if src.suffix.lower() == ".json":
        topo = normalize_topology(json.loads(src.read_text(encoding="utf-8")))
    else:
        topo = parse_topo(src)
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    output = args.output or str(base / "out" / (src.stem + ".svg"))
    result = render_to_file(topo, output, layout=args.layout,
                            show_ip=not args.no_ip,
                            show_link_labels=args.link_labels,
                            title=args.title)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
