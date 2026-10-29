# Upstream: https://github.com/llz-2002/ensptomcpfortrae (author: llz-2002).
# This copy adds UTF-8 stdio handling and bypasses system proxies for localhost.
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

import topo_build
import topo_draw

MCP_SERVER_NAME = "ensp-mcp-server"
SERVER_URL = os.environ.get("ENSP_SERVER_URL", "http://127.0.0.1:5000")
# PyInstaller 单文件模式下 __file__ 在临时目录，输出要落到 exe 旁边
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
OUT_DIR = APP_DIR / "out"


def log(message):
    """Diagnostics must never go to stdout: stdout carries JSON-RPC only."""
    sys.stderr.write(f"[eNSP-MCP] {message}\n")
    sys.stderr.flush()


def setup_utf8_stdio():
    """Windows pipes default to the locale codepage (often GBK); MCP is UTF-8."""
    for stream_name in ("stdin", "stdout"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass

mcp_server = Server(MCP_SERVER_NAME)


# ---------------------------------------------------------------- 本地拓扑工具
# 不经过 app.py，直接在 MCP 进程内解析/绘图/生成 .topo。

def _topology_info(args: dict) -> dict:
    path = Path(args["path"]).expanduser()
    topo = topo_draw.parse_topo(path)
    by_type = {}
    for d in topo["devices"]:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    names = {d["id"]: d["name"] for d in topo["devices"]}
    return {
        "source": str(path),
        "title": topo["title"],
        "device_count": len(topo["devices"]),
        "link_count": len(topo["links"]),
        "by_type": by_type,
        "devices": [{"name": d["name"], "model": d["model"], "type": d["type"], "ip": d["ip"]}
                    for d in topo["devices"]],
        "links": [{"src": names.get(l["src"], l["src"]),
                   "dst": names.get(l["dst"], l["dst"]), "label": l["label"]}
                  for l in topo["links"]],
    }


def _topology_to_mermaid(args: dict) -> dict:
    if args.get("topology"):
        topo = topo_draw.normalize_topology(args["topology"])
    else:
        topo = topo_draw.parse_topo(Path(args["path"]).expanduser())
    return {"mermaid": topo_draw.to_mermaid(topo)}


def _list_topo_files(args: dict) -> dict:
    root = Path(args.get("dir") or r"D:\ensp\eNSP\examples").expanduser()
    if not root.exists():
        raise FileNotFoundError("目录不存在: %s" % root)
    files = sorted(root.rglob("*.topo")) if args.get("recursive", True) else sorted(root.glob("*.topo"))
    return {"dir": str(root), "count": len(files),
            "files": [{"path": str(p), "size": p.stat().st_size} for p in files[:200]]}


def _create_topo(args: dict) -> dict:
    spec = args.get("topology")
    if not isinstance(spec, dict):
        raise ValueError("topology 必须是包含 devices / links 的对象")
    name = re.sub(r'[\\/:*?"<>|]', "_", str(spec.get("title") or "lab"))
    output = args.get("output") or str(OUT_DIR / (name + ".topo"))
    path = topo_build.write_topo(spec, output, layout=args.get("layout") or "auto")
    result = {"output": str(path)}
    if args.get("open_ensp"):
        result.update(topo_build.open_in_ensp(path))
    return result


def _open_topo(args: dict) -> dict:
    return topo_build.open_in_ensp(args["path"])


async def mcp_call_tool(name: str, arguments: dict):
    # trust_env=False is required: on Windows, httpx otherwise reads the
    # system proxy and sends even 127.0.0.1 traffic through it (which can
    # answer 502 and silently break every tool call).
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        if name == "scan_devices":
            params = {
                "start": arguments.get("start", 2000),
                "end": arguments.get("end", 2050)
            }
            resp = await client.get(f"{SERVER_URL}/api/devices/scan", params=params)
            return [TextContent(type="text", text=resp.text)]

        elif name == "connect_device":
            resp = await client.post(f"{SERVER_URL}/api/devices/connect", json={"port": arguments["port"]})
            return [TextContent(type="text", text=resp.text)]

        elif name == "send_command":
            resp = await client.post(f"{SERVER_URL}/api/devices/command", json={
                "path": arguments["path"],
                "command": arguments["command"]
            })
            return [TextContent(type="text", text=resp.text)]

        elif name == "disconnect_device":
            resp = await client.post(f"{SERVER_URL}/api/devices/disconnect", json={"path": arguments["path"]})
            return [TextContent(type="text", text=resp.text)]

        elif name == "get_connected_devices":
            resp = await client.get(f"{SERVER_URL}/api/devices")
            return [TextContent(type="text", text=resp.text)]

        elif name == "rename_device":
            resp = await client.post(f"{SERVER_URL}/api/devices/rename", json={
                "path": arguments["path"],
                "name": arguments["name"]
            })
            return [TextContent(type="text", text=resp.text)]

        elif name == "get_topology":
            resp = await client.get(f"{SERVER_URL}/api/topology")
            return [TextContent(type="text", text=resp.text)]

        elif name == "save_topology":
            resp = await client.post(f"{SERVER_URL}/api/topology", json=arguments.get("data", {}))
            return [TextContent(type="text", text=resp.text)]

        elif name == "topology_info":
            return [TextContent(type="text", text=json.dumps(_topology_info(arguments), ensure_ascii=False))]

        elif name == "topology_to_mermaid":
            return [TextContent(type="text", text=json.dumps(_topology_to_mermaid(arguments), ensure_ascii=False))]

        elif name == "list_topo_files":
            return [TextContent(type="text", text=json.dumps(_list_topo_files(arguments), ensure_ascii=False))]

        elif name == "create_topo":
            return [TextContent(type="text", text=json.dumps(_create_topo(arguments), ensure_ascii=False))]

        elif name == "open_topo":
            return [TextContent(type="text", text=json.dumps(_open_topo(arguments), ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": "Unknown tool"}))]


@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="scan_devices",
            description=(
                "Step 1: scan 127.0.0.1 ports for running eNSP devices. "
                "Call this first. Returns a JSON array such as "
                "[{\"port\":2000,\"path\":\"127.0.0.1:2000\",\"name\":\"127.0.0.1:2000\"}]. "
                "Default range is 2000-2050. An empty array means eNSP is not "
                "running or no device has been started."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start": {"type": "integer", "description": "Start port (default 2000)", "default": 2000},
                    "end": {"type": "integer", "description": "End port (default 2050)", "default": 2050}
                }
            }
        ),
        Tool(
            name="connect_device",
            description=(
                "Step 2: connect to one eNSP device by port. Use a port "
                "returned by scan_devices. Returns success and the device "
                "path (for example 127.0.0.1:2000), which send_command needs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "description": "Device port number"}
                },
                "required": ["port"]
            }
        ),
        Tool(
            name="send_command",
            description=(
                "Step 3: send one CLI command to a connected eNSP device. "
                "Pass path exactly as returned by connect_device (for example "
                "127.0.0.1:2000) and a single command such as 'display version'. "
                "Send commands one at a time; the output is the device's raw "
                "reply, including prompts and echoed input."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Device path (e.g. 127.0.0.1:2000)"},
                    "command": {"type": "string", "description": "Command to send"}
                },
                "required": ["path", "command"]
            }
        ),
        Tool(
            name="disconnect_device",
            description=(
                "Disconnect a device previously opened with connect_device. "
                "Pass the device path (for example 127.0.0.1:2000)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Device path (e.g. 127.0.0.1:2000)"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="get_connected_devices",
            description=(
                "List devices that are currently connected through this "
                "server. Returns a JSON array of {port, path, name}. Use it "
                "to check state before sending more commands."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="rename_device",
            description=(
                "Give a device a friendly name. This is only a label for the "
                "Web UI and scan results; it does not change the device "
                "configuration. Pass path and name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Device path"},
                    "name": {"type": "string", "description": "New device name"}
                },
                "required": ["path", "name"]
            }
        ),
        Tool(
            name="get_topology",
            description=(
                "Return the topology JSON currently held by the Web UI. It "
                "may be empty if nothing was uploaded. This is read-only."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="save_topology",
            description=(
                "Replace the topology JSON held by the Web UI. Normally only "
                "the Web UI needs this; AI agents usually should not call it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {"type": "object", "description": "Topology data object to save"}
                }
            }
        ),
        Tool(
            name="topology_info",
            description="读取 .topo，返回设备、接口、IP、链路和分类统计，不画图。",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": ".topo 文件绝对路径"}},
                "required": ["path"]
            }
        ),
        Tool(
            name="topology_to_mermaid",
            description="把 .topo 或内联拓扑转成 Mermaid 文本。",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "topology": {"type": "object"}
                }
            }
        ),
        Tool(
            name="list_topo_files",
            description="列出目录下的 .topo 文件（默认 eNSP examples）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "dir": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True}
                }
            }
        ),
        Tool(
            name="create_topo",
            description="根据设备/连线 JSON 生成 eNSP 可直接打开的 .topo；open_ensp=true 时生成后打开 eNSP。支持 AR2220/AR1220/S5700/S3700/PC/Cloud。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topology": {"type": "object", "description": "devices:[{name,model,x,y,ip,mask,gateway,mac}], links:[{src,dst,src_port,dst_port}]"},
                    "output": {"type": "string", "description": "输出 .topo 路径，默认 exe 同目录 out\\<title>.topo"},
                    "layout": {"type": "string", "enum": ["keep", "auto"], "default": "auto"},
                    "open_ensp": {"type": "boolean", "default": False}
                },
                "required": ["topology"]
            }
        ),
        Tool(
            name="open_topo",
            description="用本机 eNSP 打开指定 .topo 文件（自动查 .topo 文件关联）。",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": ".topo 文件绝对路径"}},
                "required": ["path"]
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        return await mcp_call_tool(name, arguments)
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def run_mcp_server():
    setup_utf8_stdio()
    log(f"stdio ready, forwarding to {SERVER_URL}")
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())


if __name__ == '__main__':
    log(f"starting, forwarding to {SERVER_URL}")
    asyncio.run(run_mcp_server())
