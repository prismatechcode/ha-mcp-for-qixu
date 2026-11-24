# 栖序 MCP（Home Assistant 集成）

[English](README.md)

Home Assistant 自定义集成（域名 `qixu_mcp`），把 HA 接入**栖序语音服务**。HA 主动通过 WebSocket 连到栖序接入点，在这条连接上充当 MCP 服务端，把「语音助手 → 公开」里的设备和脚本作为工具提供出去。栖序负责语音识别和大模型，听懂一句话后调用这些工具控设备。

```text
语音终端 → 栖序语音服务（识别、大模型）
                 ▲
                 │  ws:// 或 wss://，HA 主动拨出
                 │
HA + qixu_mcp ───┘  工具 = Assist 已公开的实体和脚本
```

## 它是什么、不是什么

本集成只服务栖序语音平台。

- **只出站**：HA 主动连接，不用开端口、做端口映射或公网地址。
- **不是通用 MCP 端点**：不对 Claude Desktop 等桌面客户端提供 HTTP/SSE MCP，也不是 HA 里的 MCP 客户端或对话代理。
- **范围限于 Assist**：只能用「语音助手 → 公开」里的实体和脚本，走 HA 自带的 LLM API；不提供改配置、自动化、用户等管理类工具。
- **按现场区分**：每条连接带接入令牌（`Authorization: Bearer`），可选带现场编号（`X-Qixu-Home`），一个栖序账号可接多个家庭或办公室。插件版本和 HA 版本通过 `X-Qixu-Plugin-Version`、`X-HA-Version` 上报。
- **安防动作需确认**：命中关键词（门锁、开门、撤防等）的调用先挂起，确认后才执行。
- **真实连接状态**：状态实体按实际连接显示 `connecting` / `connected` / `disconnected` / `auth_failed`。

## 要求

- Home Assistant 2026.7 及以上
- 栖序后台分配的接入点和接入令牌

## 安装

### HACS

1. HACS → 集成 → 右上角菜单 → 自定义存储库。
2. 添加 `https://github.com/prismatechcode/ha-mcp-for-qixu`，类别选 **Integration**。
3. 安装 **栖序 MCP**，重启 Home Assistant。

### 手动

把 `custom_components/qixu_mcp/` 拷到 `/config/custom_components/qixu_mcp/`，重启 Home Assistant。

## 配置

设置 → 设备与服务 → 添加集成 → 搜索「栖序 MCP」。

| 字段 | 填什么 |
|------|--------|
| 栖序接入点 | `wss://<栖序服务地址>/mcp`（`ws://` 仅用于本地测试） |
| 接入令牌 | 栖序后台分配 |
| 现场编号 | 可选。令牌只对应一个家时留空；否则填例如 `office` |
| 控制方式 | Assist。可同时勾选多个，例如通过 HA 的 MCP 客户端接入的其他 MCP 服务，其工具会一并提供给栖序 |
| 需要确认的动作关键词 | 逗号分隔，默认：门锁、开锁、开门、出车、撤防 |

提交前插件会先试连一次：令牌被拒、现场编号不匹配或接入点连不上，会直接在表单上提示，不会建出一条连不上的配置。

然后在「设置 → 语音助手 → 公开」勾选要被语音控制的设备和脚本。

检查连接：开发者工具 → 状态，搜 `qixu_mcp.`，状态为 `connected` 即已连上。

同一台 HA 可以添加多次，连不同接入点或现场编号。

## 连接管理

- **断线重连**：按指数退避加随机抖动重试，间隔从 5 秒逐步拉长到最多 5 分钟；连接稳定一分钟后间隔重置。
- **令牌失效**：栖序返回 401 或 403 时停止重试，状态变为 `auth_failed`，HA 弹出「重新配置」，填入新令牌即可恢复。
- **诊断信息**：设置 → 设备与服务 → 栖序 MCP → ⋮ → 下载诊断信息，包含插件和 HA 版本、连接状态、最近错误和已公开的工具名。令牌会被隐去，接入点只保留协议、主机和路径。

## 安防确认

工具名、脚本显示名或参数里出现关键词时，插件不执行，返回：

```json
{"requires_confirmation": true, "confirm_id": "a1b2c3d4", "action": "打开门锁", "speech": "这是安防动作：打开门锁。请确认后再执行。"}
```

栖序服务调用 `QixuConfirmAction` 并带上 `confirm_id` 才会执行，30 秒内有效，只能用一次。

插件保证「没有这一步就不会执行」；确认是不是用户亲口说的，由栖序服务端负责。

## 隐私

- 栖序服务只能看到 Assist 已公开的实体和脚本。
- 接入令牌保存在集成配置里，只发往你配置的接入点。
- 除配置的接入点外，不向任何地方发送数据。

## 开发

`hub/` 是本地模拟的栖序接入端，用于没有正式后台时联调。它不属于集成本身，HACS 不会安装它。

```powershell
python hub/qixu_hub.py --port 8791 --token <令牌>
```

| 接口 | 用途 |
|------|------|
| `ws://<本机>:8791/mcp` | 填到集成的接入点 |
| `GET /homes` | 已连上的现场 |
| `GET /homes/{home}/tools` | 该现场的工具 |
| `POST /homes/{home}/call` | 直接调用工具 |
| `POST /v1/voice` | 发文字指令，例如 `{"text": "打开办公室灯"}` |

HTTP 接口要带 `Authorization: Bearer <令牌>`。语音接口从 `hub/config.json` 读取大模型密钥（参考 `hub/config.example.json`）。

### 测试

```powershell
python -m venv .venv-test
.\.venv-test\Scripts\python -m pip install "mcp==1.26.0" "anyio==4.13.0" aiohttp
.\.venv-test\Scripts\python tests\test_hub_e2e.py
.\.venv-test\Scripts\python tests\test_plugin_units.py
```

`tests/fake_ha.py` 用和 HA 相同版本的 MCP 库模拟一台 HA，配合插件真实的确认逻辑，验证连接、鉴权、列工具、普通调用直通和安防挂起。`tests/test_plugin_units.py` 覆盖退避间隔、请求头、接入点脱敏、动作名称，以及对本地 WebSocket 服务的试连。配置界面、重新认证、诊断信息和读取 Assist 工具需要装到真机验证。

## 发版

在 GitHub 上用 `v0.2.0` 这样的 tag 发布 Release，`release.yml` 会把 manifest 版本改成 tag 版本，打包 `ha-mcp-for-qixu.zip` 并上传到该 Release。

## 许可

MIT
