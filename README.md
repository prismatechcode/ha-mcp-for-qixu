# ha-mcp-for-qixu

Home Assistant 插件（域名 `qixu_mcp`）：HA 主动连到栖序语音服务的接入点，在这条连接上当 MCP 服务端，把「设置 → 语音助手 → 公开」里的设备和脚本作为工具提供出去。栖序那边的大模型听懂一句话后，通过这条连接调用工具控设备。

```text
语音终端 → 栖序语音服务（识别、大模型）
                 ▲
                 │  ws:// 或 wss://，HA 主动拨出
                 │
HA + qixu_mcp ───┘  工具 = Assist 已公开的实体和脚本
```

HA 不需要开放端口，也不用公网地址。接入需携带令牌（`Authorization: Bearer`）和现场编号（`X-Qixu-Home`）。命中安防关键词时先返回确认编号，确认后才执行。

## 安装

1. 把 `custom_components/qixu_mcp/` 拷到 HA 的 `/config/custom_components/qixu_mcp/`，或运行 `scripts/install.ps1`（走 SSH 插件的 22222 端口）。
2. 重启 Home Assistant。
3. 设置 → 设备与服务 → 添加集成 → 搜索「栖序 MCP」，填写：

| 字段 | 填什么 |
|------|--------|
| 栖序接入点 | `ws://<栖序服务地址>:8791/mcp`，正式环境用 `wss://` |
| 接入令牌 | 栖序后台分配 |
| 现场编号 | 例如 `office` |
| 控制方式 | Assist |
| 需要确认的动作关键词 | 默认即可 |

4. 设置 → 语音助手 → 公开：勾选要被语音控制的设备和脚本。
5. 开发者工具 → 状态里搜 `qixu_mcp.`，状态为 `connected` 表示连上了。

同一台 HA 可以加多条，每条连不同的接入点或现场编号。

## 安防确认

大模型调用的工具，如果工具名、脚本显示名或参数里出现关键词，插件不执行，返回：

```json
{"requires_confirmation": true, "confirm_id": "a1b2c3d4", "action": "打开门锁", "speech": "这是安防动作：打开门锁。请确认后再执行。"}
```

用户说「确认」后，栖序服务调用 `QixuConfirmAction`，带上 `confirm_id`，30 秒内有效，只能用一次。

插件能保证「不经过确认就不会执行」，但分不清确认是不是用户亲口说的。要求用户亲口确认这一步，由栖序服务端负责：只有识别到用户说了确认，才发 `QixuConfirmAction`。

## 本地接入端（开发用）

`hub/qixu_hub.py` 是一个最小的栖序接入端，用来在没有正式后台时联调：

```powershell
# 工作目录用 hub/，以便加载 voice_agent
python hub/qixu_hub.py --port 8791 --token <令牌>
# 或
.\scripts\restart_hub.ps1
```

| 接口 | 说明 |
|------|------|
| `ws://<本机>:8791/mcp` | 填到 HA 插件里的接入点 |
| `GET /health` | 健康检查与已连接现场 |
| `GET /homes` | 已连上的现场 |
| `GET /homes/{home}/tools` | 该现场的工具；加 `?refresh=1` 重新拉取 |
| `POST /homes/{home}/call` | `{"name": "...", "arguments": {...}}` 调用工具 |
| `POST /v1/voice` | 自然语言控家（默认连 `office`，可用 `?home=`） |
| `POST /homes/{home}/voice` | 指定现场的自然语言控家 |

HTTP 接口同样要带 `Authorization: Bearer <令牌>`。

### 语音接口

```http
POST /v1/voice
Authorization: Bearer <令牌>
Content-Type: application/json

{"text":"打开办公室灯","session_id":"可选"}
```

流程：规则快路径（开/关办公室灯、空调等）→ 否则百炼大模型选工具 → 经 MCP 调 HA。

可选 `hub/config.json`（参考 `hub/config.example.json`）：

```json
{
  "deepseek_api_key": "...",
  "deepseek_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "deepseek_model": "qwen-plus"
}
```

未放 `hub/config.json` 时，会回退读取 `ha-voice-assistant/config.json`。

## 测试

```powershell
python -m venv .venv-test
.\.venv-test\Scripts\python -m pip install "mcp==1.26.0" "anyio==4.13.0" aiohttp
.\.venv-test\Scripts\python tests\test_hub_e2e.py
```

`tests/fake_ha.py` 用和 HA 2026 相同版本的 MCP 库模拟一台 HA，配合插件里真实的确认逻辑，验证连接、鉴权、列工具、普通动作直通、安防动作确认。它不覆盖插件里依赖 HA 的部分（配置界面、读取 Assist 工具），那部分要装到真机验证。

## 发版

1. 推送到公开 GitHub 仓库，`hacs.yaml` 和 `hassfest.yaml` 两个检查需通过。
2. 在 GitHub 上用 `v0.1.0` 这样的 tag 发布 Release，`release.yml` 会把 `manifest.json` 的版本改成 tag 版本，打包 `ha-mcp-for-qixu.zip` 并上传到这个 Release。
3. 用户在 HACS → 自定义存储库中添加仓库地址（类别选 Integration）即可安装和更新。

## 许可

MIT。
