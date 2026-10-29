# eNSP MCP 便携版

把华为 eNSP 交给 AI 操作的 MCP 服务器，打包成单个 `eNSP-MCP.exe`，目标电脑不需要安装 Python。

源码来自上游 [llz-2002/ensptomcpfortrae](https://github.com/llz-2002/ensptomcpfortrae)，本仓库是在其基础上做的便携化适配：

- PyInstaller 单文件打包（win32 / win64）
- Web 服务和 MCP 服务合并到一个进程
- 修复 Windows 下 stdio 的 UTF-8 编码、系统代理导致本机 127.0.0.1 请求返回 502 的问题
- 新增拓扑工具：读取/生成 `.topo`、按 JSON 生成 eNSP 拓扑并打开

## 功能

设备侧（沿用上游）：

- `scan_devices` / `connect_device` / `send_command` / `disconnect_device`
- `get_connected_devices` / `rename_device` / `get_topology` / `save_topology`

拓扑侧（新增）：

| 工具 | 作用 |
|---|---|
| `create_topo` | 按 JSON 生成 eNSP 可直接打开的 `.topo`，`open_ensp=true` 时直接拉起 eNSP |
| `open_topo` | 用本机 eNSP 打开 `.topo` |
| `topology_info` | 读取 `.topo`，返回设备/接口/IP/链路摘要 |
| `topology_to_mermaid` | 转 Mermaid 文本 |
| `list_topo_files` | 列出目录下的 `.topo` |

`create_topo` 支持 AR2220、AR1220、S5700、S3700、PC、Cloud；只生成拓扑文件，不启动设备、不下发配置。

## 构建

```powershell
# 32 位（需要联网下载 Python 3.11.9 embeddable）
powershell -ExecutionPolicy Bypass -File build32\build32.ps1

# 64 位
powershell -ExecutionPolicy Bypass -File build64.ps1
```

首次构建会把 Python 运行时下载到 `build32\toolchain\py311-32` 或 `toolchain\py311-64`，依赖见 `build32\requirements32.txt`。产物分别是 `build32\dist\eNSP-MCP.exe` 和 `dist64\eNSP-MCP.exe`。

国内网络如果 python.org 下载卡住，脚本会自动切到华为云镜像；也可以手动把对应 embeddable zip 放到脚本预期位置，脚本会跳过下载。

## 生成拓扑的 JSON 示例

```json
{
  "title": "STP 实验",
  "devices": [
    {"name": "S1", "model": "S3700", "mac": "4c1f-cc73-c72d"},
    {"name": "PC1", "model": "PC", "ip": "10.1.1.1", "mask": "255.255.255.0"}
  ],
  "links": [
    {"src": "S1", "dst": "PC1", "src_port": "Ethernet0/0/10", "dst_port": "Ethernet0/0/1"}
  ]
}
```

## 目录

```
build32/
  src/                 # 主程序、MCP 服务、拓扑模块、Web UI 静态文件
  build32.ps1          # 32 位构建脚本
  requirements32.txt
  version_info.txt
build64.ps1            # 64 位构建脚本（复用 build32/src）
```

## 说明

- `open_topo` 通过 `explorer.exe` 交给 shell 启动 eNSP，eNSP 的父进程是资源管理器，不会随命令进程结束而被杀掉。
- 运行 exe 需要本机已安装 eNSP；打开 `.topo` 依赖系统的 `.topo` 文件关联。
- 上游仓库未在本仓库声明许可证；本仓库只包含便携化适配和打包脚本，使用前请遵循上游仓库说明。
## 拓扑与插卡的 AI 标准流程

> 原则：拓扑归拓扑，配置归配置；插卡必须由用户在 eNSP 里完成并保存。

1. **生成拓扑**：用 `create_topo` 只生成设备、连线和 PC 的 IP，不写任何 VRP 命令。
2. **判断是否需要插卡**：如果目标接口是 `Ethernet1/0/x`、`GE1/0/x` 这类扩展卡端口（例如 AR1220 的 `Ethernet1/0/1` 需要 8FE1GE），不要猜卡槽的 `type` 和端口索引。
3. **让用户插卡**：
   - 明确告诉用户：哪台设备、哪个槽位、插哪张卡（型号/卡名）。
   - 要求用户插好后按 `Ctrl+S` 保存，然后关闭 eNSP。
   - 等用户确认“已保存并关闭”再继续。
   - 禁止 AI 用 `taskkill` / `Stop-Process` 关闭 eNSP；未保存就关闭会丢插卡改动。
4. **读硬件**：读取用户保存的 `.topo`，从 `<slot isMainBoard="0" id="..." type="..." />` 拿到卡槽和卡类型，从设备槽位/接口表拿到最终接口顺序；以文件和 `display interface brief` 为准。
5. **接线**：按接口名重新计算 `srcIndex/tarIndex`，重写 `<lines>`；不要沿用插卡前的旧下标。
6. **重新打开**：用 `open_topo` 打开修改后的 `.topo`。
7. **让用户开机**：用户全选设备 → 启动，等绿色三角/端口出现。
8. **AI 配置**：`scan_devices` → `connect_device` → `send_command` 逐条下发；配完 `save`。
9. **禁止事项**：
   - 不要把 VRP 命令写进 `.topo`
   - 不要自动关闭 eNSP
   - 不要在设备未启动时下发配置
   - 不要猜卡的 `type` 或接口索引