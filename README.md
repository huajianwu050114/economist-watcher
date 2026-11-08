# Economist Watcher · 《经济学人》定期监测器

> 无 AI、无需安装 Python 到本地电脑、无付费 API；核心仅使用 Python 标准库与 GitHub Actions。
>
> **当前完成：新刊监测、去重、GitHub Issues 通知、失败重试、授权 PDF 下载接口。**
> **尚未验证：Magazine Lib 的动态 PDF 按钮能否无人值守下载，且不能据此确认它具有版权授权。**

## 1. 最快上线（Windows，推荐）

1. 解压 ZIP 到任意不含敏感数据的文件夹。
2. 确认已安装 Git 和 GitHub CLI：

   ```powershell
   git --version
   gh --version
   ```

   若缺失，打开 PowerShell 并执行：

   ```powershell
   winget install --id Git.Git --exact
   winget install --id GitHub.cli --exact
   ```

   安装后**重新打开 PowerShell**。
3. 在解压出来的 `economist_watcher` 目录中打开 PowerShell，执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
   ```

   脚本会调用 GitHub 官方 CLI，让你在浏览器登录，创建一个**私有仓库**并上传这份工程。脚本不会索取你的 GitHub 密码或将凭据写进本项目。首次登录需你自己授权。
4. 脚本结束时会显示 `https://github.com/<你的账号>/economist-watcher/actions`。进入后选 **Economist Watcher → Run workflow → Run workflow**。
5. 进入这次执行结果，打开 **Summary** 查看新刊列表；进入仓库 **Issues** 可查看新刊通知。首次运行只标记最新一期为新，其他旧刊作为去重基线；第二次运行没有新刊就直接报告 0 条。

> **你不需要把电脑开着**。定时任务由 GitHub 的临时云端 Runner 执行。每周三、周日，北京时间 **09:37**，自动检查两次。GitHub 有时会延迟或跳过定时运行，因此不是硬实时保证。

## 2. 当前默认行为

- 监控页面：`https://magazinelib.com/all/the-economist/`（直接公开列表，首选）
- 备用来源：`https://rsshub.app/magazinelib/latest-magazine/the+economist`（RSSHub，当前无法在编写环境中完成实时可用性验证）
- 地区：**Asia Edition**（仅亚洲版）。可在 `.github/workflows/economist.yml` 中把 `EDITION: asia` 改为 `all` / `uk` / `usa` / `europe` / `middle-east-africa`。
- 文件：`data/seen.json` 只记录已见期号和处理状态，首次执行由程序生成，再由 GitHub Actions 自动提交保存到仓库。
- 通知：使用自动生成的 GitHub Issues（无需另配密钥）；如有 Telegram Bot，可选配额外推送。
- 没有更新：不下载、不创建新 Issue、不提交无意义的状态更改。
- 页面解析为空、网络异常：明确报错，不会错误地输出“没有更新”。

## 3. PDF 自动下载：功能接口已写，仍需要合法可用的来源

Magazine Lib 的页面提供动态下载按钮及 Telegram 入口；这**不是**已经验证可自动下载的直接 PDF 地址。程序不会破解访问控制、自动抓取 Telegram 文件或者冒充用户绕过付费限制。

当你拥有有权访问的 **HTTPS PDF 直链**，可以在 GitHub 私有仓库配置 Secret：

**Settings → Secrets and variables → Actions → New repository secret**

- 名称：`PDF_URL_MAP_JSON`
- 值示例（将示例 URL 换成你的合法 PDF 文件链接）：

  ```json
  {"2026-10-24:asia":"https://your-authorized-storage.example.com/economist_2026-10-24.pdf"}
  ```

如果你的**合法 PDF 来源**提供稳定的按日期命名的下载地址，也可改用 Secret `PDF_URL_TEMPLATE`（例如 `https://your-authorized-storage.example.com/economist/{date}_{edition}.pdf`），这样后续新刊就不用逐一配置链接。该模板仅在来源确实提供这种规则、且你有权获取时才有效。

下次运行时，程序会自动：检测此期是否已下载 → 访问 HTTPS 链接 → 限制 80 MiB → 验证 PDF 头 → 计算 SHA256 → 保存为 `The_Economist_2026-10-24_asia.pdf`。

**注意**：这份映射只是一种接入已授权 PDF 的方式；并不意味着它能自动猜出未来每一期的 URL。只有合法来源具备有效模板/API 时，未来每期才能真正无人值守下载；目前没有验证 Magazine Lib 提供这种能力。

成功文件会作为 GitHub Actions 的 **Artifacts** 暂存 30 天，可进入执行详情下载。请勿将版权文件推送到公开仓库。若你希望关机时自动保存到长期云盘，需要另外接入受控私有存储；**Artifacts 不是永久归档**。

## 4. 可选 Telegram 新刊通知

在 GitHub 仓库 Secrets 里增加：

- `TG_BOT_TOKEN`：你从 `@BotFather` 创建的机器人 Token。
- `TG_CHAT_ID`：你的私聊 ID 或群 ID（机器人须有发消息权限）。

配置后会同时发送 GitHub Issue 通知和 Telegram 文本通知。不要把 Token 写进项目源码或聊天记录。

## 5. 开发者本地验证

无需第三方依赖：

```powershell
python -m unittest discover -s tests -v
# 使用内置 HTML 样本演示第一次“发现新刊”，不联网、不发送通知
python monitor.py --edition asia --fixture tests/fixtures/magazinelib.html --no-notify --state data/demo.json
# 再执行一次，预期“本次新增：0”
python monitor.py --edition asia --fixture tests/fixtures/magazinelib.html --no-notify --state data/demo.json
# 真正联网检测
python monitor.py --edition asia --no-notify
```

`data/demo.json` 可在演示后删除；不要把它当成真实网站扫描历史。

## 6. 运行限制与故障处理

- 这是一个网页监测器，不是官方《经济学人》订阅客户端；实际更新会受第三方网站上架时间影响。
- RSSHub 路由在文档中存在，但公共实例可能限流、不可用；首选直接分类列表，备用 RSSHub。
- 如果两个来源都失效，运行会失败并保留旧状态。GitHub Actions 执行日志会解释原因。
- GitHub 官方说明：定时执行可能延迟、部分高负载时跳过；公开仓库长期无活动的 schedule 可能被停用。使用私有仓库更符合个人用途。
- `data/seen.json` 放在 Git 仓库中，而不是 Runner 临时目录中，才可跨定时任务去重。
- 云端下载并不代表关机的 Windows 电脑收到文件。要真正多设备永久同步，需要接入 OneDrive/其他私人云盘的授权 API。
- **版权**：自动化只处理网页公开的刊物索引与经确认有权获取的文件。是否可以下载和保存具体刊物，以出版方授权及适用法律为准。

## 7. 项目结构

```text
.github/workflows/economist.yml   GitHub 每周三、日定时任务
sources.py                        HTML / RSSHub 期号发现、识别地区与日期
monitor.py                        去重、通知、授权 PDF 下载、报告生成
tests/                            离线单元测试和测试数据
data/.gitkeep                      持久化记录位置
deploy.ps1                         Windows 一键创建私有仓库部署
```

## 8. 调整时间

编辑 `.github/workflows/economist.yml` 中的：

```yaml
on:
  schedule:
    - cron: '37 9 * * 3,0'
      timezone: 'Asia/Shanghai'
```

最后的 `3,0` 表示周三、周日。`workflow_dispatch` 则允许你任何时候手动运行一次。

## 9. 后续可以增加的特性（本版没有冒充已完成）

1. 经确认的出版社/图书馆合法 PDF API → 自动解析每期下载链接。
2. OneDrive/rclone 永久归档 → Windows、平板自动同步。
3. 更可靠的通知告警、操作仪表盘、全部版本偏好配置。
4. 作为 Horizon 的自定义信息源输出。
