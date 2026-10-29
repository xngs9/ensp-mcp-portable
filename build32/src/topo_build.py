# -*- coding: utf-8 -*-
"""
根据设备/连线 JSON 生成 eNSP 能直接打开的 .topo 工程，并可拉起 eNSP。

只生成拓扑文件，不配置设备。

命令行：
    python topo_build.py spec.json -o out/lab.topo --open
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import subprocess
import sys
import uuid
from pathlib import Path

import topo_draw

ENSP_EXE = Path(r"D:\ensp\eNSP\eNSP_Client.exe")
TOPO_VERSION = "1.3.00.100"

# 型号 -> (槽位 XML, 可用端口数, MAC 前缀)
_SLOT_AR2220 = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="1" />
                <interface sztype="Ethernet" interfacename="GE" count="2" />
            </slot>"""

_SLOT_AR1220 = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="2" />
                <interface sztype="Ethernet" interfacename="Ethernet" count="8" />
                <interface sztype="Ethernet" interfacename="Ethernet" count="8" />
                <interface sztype="Ethernet" interfacename="GE" count="1" />
            </slot>
            <slot isMainBoard="0" id="1" type="4" />"""

_SLOT_S5700 = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="24" />
            </slot>"""

_SLOT_S3700 = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="Ethernet" count="22" />
                <interface sztype="Ethernet" interfacename="GE" count="2" />
            </slot>"""

_SLOT_PC = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="1" />
            </slot>"""

_SLOT_CLOUD = """            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="Ethernet" count="3" />
                <interface sztype="Ethernet" interfacename="GE" count="0" />
                <interface sztype="Serial" interfacename="Serial" count="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="1" remoteDisplayNo="2" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="1" remoteDisplayNo="3" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="2" remoteDisplayNo="1" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="2" remoteDisplayNo="3" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="3" remoteDisplayNo="1" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
                <interfaceMap sztype="Ethernet" interfacename="Ethernet" displayNo="3" remoteDisplayNo="2" adapterUid="" isOpen="0" udpPort="0" peerIPAdd="0.0.0.0" peerIP="0" peerPort="0" />
            </slot>"""

MODELS = {
    "AR2220": {"slots": _SLOT_AR2220, "ports": 2, "mac": "00-E0-FC", "kind": "router"},
    "AR1220": {"slots": _SLOT_AR1220, "ports": 19, "mac": "00-E0-FC", "kind": "router"},
    "S5700": {"slots": _SLOT_S5700, "ports": 24, "mac": "4C-1F-CC", "kind": "switch"},
    "S3700": {"slots": _SLOT_S3700, "ports": 24, "mac": "4C-1F-CC", "kind": "switch"},
    "PC": {"slots": _SLOT_PC, "ports": 1, "mac": "54-89-98", "kind": "pc"},
    "Cloud": {"slots": _SLOT_CLOUD, "ports": 3, "mac": "", "kind": "cloud"},
}

PC_SETTINGS = (" -simpc_ip {ip}  -simpc_mask {mask}  -simpc_gateway {gw}  -simpc_mac {mac}"
               "  -simpc_mc_dstip 0.0.0.0  -simpc_mc_dstmac 00-00-00-00-00-00"
               "  -simpc_dns1 0.0.0.0  -simpc_dns2 0.0.0.0  -simpc_ipv6 ::  -simpc_prefix 128"
               "  -simpc_gatewayv6 ::  -simpc_dhcp_state 0  -simpc_dhcpv6_state 0"
               "  -simpc_dns_auto_state 0 ")


def _mac(prefix: str, index: int) -> str:
    rnd = random.Random(20261029 + index)
    return "%s-%02X-%02X-%02X" % (prefix, rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))


def normalize_mac(value: str) -> str:
    """接受 4c1f-cc73-c72d / 4C:1F:CC:73:C7:2D 等写法，统一成 4C-1F-CC-73-C7-2D。"""
    hexs = re.sub(r"[^0-9A-Fa-f]", "", value or "")
    if len(hexs) != 12:
        raise ValueError("MAC 格式不对: %s" % value)
    return "-".join(hexs[i:i + 2].upper() for i in range(0, 12, 2))


def port_index(model: str, port_name: str) -> int:
    """把 Ethernet0/0/10、GE0/0/1 这类接口名转成 eNSP 的 srcIndex/tarIndex（从 0 开始）。"""
    m = re.search(r"(\d+)\s*$", port_name or "")
    if not m:
        raise ValueError("接口名看不懂: %s" % port_name)
    n = int(m.group(1))
    if n < 1:
        raise ValueError("接口编号从 1 开始: %s" % port_name)
    idx = n - 1
    upper = (port_name or "").upper().replace(" ", "")
    if model == "S3700":
        # Ethernet0/0/1-22 在前，GE0/0/1-2 在后
        if "ETHERNET" in upper:
            return idx
        if upper.startswith("GE"):
            return 22 + idx
    elif model == "AR1220":
        if upper.startswith("GE"):
            return idx
        return 2 + idx
    return idx


def _prepare(spec: dict, layout: str) -> dict:
    """转成 topo_draw 认识的拓扑结构，并完成布局。"""
    raw_devices = spec.get("devices") or []
    if not raw_devices:
        raise ValueError("devices 不能为空")

    names = set()
    devices = []
    for i, d in enumerate(raw_devices):
        name = str(d.get("name") or "D%d" % (i + 1))
        if name in names:
            raise ValueError("设备名重复: %s" % name)
        names.add(name)
        model = str(d.get("model") or "PC")
        if model not in MODELS:
            raise ValueError("不支持的型号 %s；可用: %s" % (model, ", ".join(sorted(MODELS))))
        devices.append({
            "id": name,
            "name": name,
            "model": model,
            "type": MODELS[model]["kind"],
            "x": float(d.get("x") or 0),
            "y": float(d.get("y") or 0),
            "ip": str(d.get("ip") or ""),
            "mask": str(d.get("mask") or "255.255.255.0"),
            "gateway": str(d.get("gateway") or "0.0.0.0"),
            "mac": str(d.get("mac") or ""),
        })

    links = []
    for l in spec.get("links") or []:
        src, dst = str(l.get("src")), str(l.get("dst"))
        if src not in names or dst not in names:
            raise ValueError("连线引用了不存在的设备: %s - %s" % (src, dst))
        if src == dst:
            raise ValueError("设备不能连自己: %s" % src)
        links.append({
            "src": src, "dst": dst, "label": str(l.get("label") or ""),
            "src_port": str(l.get("src_port") or ""),
            "dst_port": str(l.get("dst_port") or ""),
        })

    topo = {"title": str(spec.get("title") or "eNSP 拓扑"), "devices": devices, "links": links}
    if layout == "auto" or not topo_draw._has_positions(topo):
        topo_draw.auto_layout(topo)
    else:
        topo_draw._normalize_positions(topo, margin=120)

    # 端口用量校验
    used: dict[str, int] = {}
    for l in links:
        for key in ("src", "dst"):
            used[l[key]] = used.get(l[key], 0) + 1
    for d in devices:
        limit = MODELS[d["model"]]["ports"]
        if used.get(d["name"], 0) > limit:
            raise ValueError("%s(%s) 最多 %d 个端口，当前连了 %d 条线"
                             % (d["name"], d["model"], limit, used[d["name"]]))
    return topo


def build_topo(spec: dict, layout: str = "auto") -> str:
    topo = _prepare(spec, layout)
    devices = topo["devices"]
    by_name = {d["name"]: d for d in devices}

    # 控制台端口从 2000 起，PC/Cloud 用 0
    next_port = 2000
    for i, d in enumerate(devices):
        d["id"] = str(uuid.uuid4()).upper()
        if d["model"] in ("PC", "Cloud"):
            d["com_port"] = 0
        else:
            d["com_port"] = next_port
            next_port += 1
        if d.get("mac"):
            d["system_mac"] = normalize_mac(d["mac"])
        elif MODELS[d["model"]]["mac"]:
            d["system_mac"] = _mac(MODELS[d["model"]]["mac"], i)
        else:
            d["system_mac"] = ""
        d["bootmode"] = 1 if d["model"] == "PC" else 0

    # 端口序号：优先用 src_port/dst_port 指定，没给就按顺序取空闲端口
    used_ports: dict[str, set] = {d["name"]: set() for d in devices}
    auto_next: dict[str, int] = {d["name"]: 0 for d in devices}
    for l in topo["links"]:
        for side in ("src", "dst"):
            name = l[side]
            model = by_name[name]["model"]
            port_name = l.get(side + "_port") or ""
            if port_name:
                idx = port_index(model, port_name)
            else:
                idx = auto_next[name]
                while idx in used_ports[name]:
                    idx += 1
                auto_next[name] = idx + 1
            if idx < 0 or idx >= MODELS[model]["ports"]:
                raise ValueError("%s(%s) 没有 %s 这个端口（有效序号 0-%d）"
                                 % (name, model, port_name or idx, MODELS[model]["ports"] - 1))
            if idx in used_ports[name]:
                raise ValueError("%s(%s) 的端口 %s 被重复连接" % (name, model, port_name or idx))
            used_ports[name].add(idx)
            l[side + "_index"] = idx

    out = ['<?xml version="1.0" encoding="UNICODE" ?>',
           '<topo version="%s">' % TOPO_VERSION,
           '    <devices>']
    for d in devices:
        settings = ""
        if d["model"] == "PC":
            settings = PC_SETTINGS.format(ip=d["ip"] or "0.0.0.0", mask=d["mask"],
                                          gw=d["gateway"], mac=d["system_mac"])
        attrs = {
            "id": d["id"], "name": d["name"], "poe": "0", "model": d["model"],
            "settings": settings, "system_mac": d["system_mac"],
            "com_port": str(d["com_port"]), "bootmode": str(d["bootmode"]),
            "cx": "%.6f" % d["x"], "cy": "%.6f" % d["y"],
            "edit_left": str(int(round(d["x"] + 27))), "edit_top": str(int(round(d["y"] + 54))),
        }
        attr_text = " ".join('%s="%s"' % (k, html.escape(v, quote=True)) for k, v in attrs.items())
        out.append("        <dev %s>" % attr_text)
        out.append(MODELS[d["model"]]["slots"])
        out.append("        </dev>")

    out.append("    </devices>")
    out.append("    <lines>")
    for l in topo["links"]:
        a, b = by_name[l["src"]], by_name[l["dst"]]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        dist = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / dist, dy / dist
        sx, sy = a["x"] + ux * 30, a["y"] + uy * 30
        tx, ty = b["x"] - ux * 30, b["y"] - uy * 30
        out.append('        <line srcDeviceID="%s" destDeviceID="%s">' % (a["id"], b["id"]))
        out.append(
            '            <interfacePair lineName="Copper" srcIndex="%d" '
            'srcBoundRectIsMoved="0" srcBoundRect_X="%.6f" srcBoundRect_Y="%.6f" '
            'srcOffset_X="0.000000" srcOffset_Y="0.000000" '
            'tarIndex="%d" tarBoundRectIsMoved="0" tarBoundRect_X="%.6f" tarBoundRect_Y="%.6f" '
            'tarOffset_X="0.000000" tarOffset_Y="0.000000" />'
            % (l["src_index"], sx, sy, l["dst_index"], tx, ty)
        )
        out.append("        </line>")
    out.append("    </lines>")
    out.append("    <shapes />")
    out.append("    <txttips />")
    out.append("</topo>")
    return "\r\n".join(out) + "\r\n"


def write_topo(spec: dict, output: str | Path, layout: str = "auto") -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_topo(spec, layout=layout), encoding="utf-8", newline="")
    return out.resolve()


def find_ensp_exe() -> Path | None:
    """优先用 .topo 的文件关联，找不到再试常见安装路径。"""
    if ENSP_EXE.exists():
        return ENSP_EXE
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"topofile\shell\open\command") as key:
            command, _ = winreg.QueryValueEx(key, "")
        m = re.search(r'"([^"]+\.exe)"', command, re.I)
        if m and Path(m.group(1)).exists():
            return Path(m.group(1))
    except Exception:
        pass
    for candidate in (
        r"C:\Program Files\Huawei\eNSP\eNSP_Client.exe",
        r"C:\Program Files (x86)\Huawei\eNSP\eNSP_Client.exe",
        r"D:\ensp\eNSP\eNSP_Client.exe",
    ):
        if Path(candidate).exists():
            return Path(candidate)
    return None


def open_in_ensp(path: str | Path) -> dict:
    """用 explorer.exe 交给 shell 打开，避免 eNSP 成为当前命令进程的子进程。

    Claude Code / 终端工具常在 Job Object 里跑命令，命令结束会连带杀掉子进程。
    经 explorer 启动的 eNSP 挂在资源管理器下，不会跟着退出。
    """
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError("找不到拓扑文件: %s" % target)

    explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
    if explorer.exists():
        subprocess.Popen([str(explorer), str(target)])
        return {
            "opened": str(target),
            "method": "explorer",
            "note": "已交给资源管理器启动，eNSP 不会随命令进程退出",
        }

    exe = find_ensp_exe()
    if exe is None:
        raise FileNotFoundError("找不到 eNSP_Client.exe（可先手动双击 .topo 建立关联）")
    proc = subprocess.Popen([str(exe), str(target)], cwd=str(exe.parent))
    return {"opened": str(target), "method": "direct", "pid": proc.pid, "exe": str(exe)}


def app_dir() -> Path:
    """PyInstaller 单文件模式下 __file__ 在临时目录，输出应落在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description="根据 JSON 生成 eNSP .topo，可选直接打开")
    ap.add_argument("spec", help="JSON 文件")
    ap.add_argument("-o", "--output", help="输出 .topo 路径")
    ap.add_argument("--layout", choices=["keep", "auto"], default="auto")
    ap.add_argument("--open", action="store_true", help="生成后拉起 eNSP")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output = args.output or str(app_dir() / "out" / ((spec.get("title") or "lab") + ".topo"))
    path = write_topo(spec, output, layout=args.layout)
    result = {"output": str(path)}
    if args.open:
        result.update(open_in_ensp(path))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
