# 打包为 Windows EXE（面向老年用户）

本文档说明如何把 easy-tdx + Vue 前端打包成单一 Windows EXE，让老人双击即可
使用量化回测界面，无需安装 Python、Node 或任何依赖。

## 给最终用户（老人 / 量化初学者）

### 下载

到 [Releases 页面](https://github.com/<owner>/easy_tdx/releases) 下载最新的
`easy-tdx-<版本号>-windows.exe`（约 80-150MB）。

### 运行

1. 双击 `easy-tdx-<版本号>-windows.exe`
2. 首次运行 Windows 会弹"已保护你的电脑"（蓝色 SmartScreen 窗口）：
   - 点击 **更多信息**
   - 点击 **仍要运行**
   - （Phase 2 引入代码签名后会消除此提示）
3. 等待 2-5 秒（EXE 首次解压），浏览器会自动打开
   `http://localhost:8000`
4. 即可看到回测界面，开始使用

### 关闭

直接关闭浏览器标签页**不会**停止后台服务。完整退出请：

- 在任务管理器结束 `easy-tdx.exe` 进程，或
- 在命令行运行 `taskkill /IM easy-tdx.exe /F`

### 已知限制

- **必须联网**：在线行情数据需要连接通达信服务器。
- **离线 .day 读取需要通达信**：若没安装 Windows 版通达信，离线读取本地
  数据功能不可用；在线行情不受影响。
- **收藏的策略不会丢**：策略保存在 `~/.easy_tdx/strategies.db`，跨重启保留。
  升级 EXE 时该文件不会被覆盖。

### 排查问题

双击后没反应（浏览器没打开）：

1. 打开命令提示符（Win+R 输入 `cmd`）
2. 拖拽 EXE 到命令行，加 ` serve`，回车
3. 查看报错信息（通常是端口 8000 被占用，改用 `--port 8001`）

---

## 给开发者：本地构建 EXE

### 前置

- Windows 10/11（PyInstaller 不支持跨平台编译）
- Python 3.10+
- Node.js 20+
- 项目已 `pip install -e ".[web]"` 安装到当前环境

### 步骤

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 构建前端
cd web-ui
npm ci
npm run build
cd ..

# 3. 构建 EXE
pyinstaller easy_tdx.spec --noconfirm

# 4. 产物
ls -lh dist/easy-tdx.exe
```

双击 `dist/easy-tdx.exe` 验证：浏览器自动打开，能跑通一次内置策略回测。

### 调试

`.spec` 默认 `console=False`（无黑窗）。排查启动失败时：

```bash
# 临时改 console=True 重新打包，或在命令行运行看 stderr
dist/easy-tdx.exe serve --no-open-browser
```

---

## GitHub Actions 自动发版

打 tag 触发：

```bash
git tag v1.19.0
git push origin v1.19.0
```

`.github/workflows/release.yml` 会自动：

1. 在 `windows-latest` runner 上构建前端 + EXE
2. 重命名为 `easy-tdx-<版本>-windows.exe`
3. 创建 GitHub Release 并上传 EXE

该 workflow 与 `publish.yml`（PyPI）**完全独立**：即使 PyPI 发布失败，EXE
照样能发布。两个 workflow 共享 `v*` tag 触发器但互不依赖。

---

## 当前限制（Phase 1）

| 项 | 状态 | 说明 |
|---|---|---|
| Windows EXE | ✅ | 单文件，双击即用 |
| 代码签名 | ❌ | 未签名，SmartScreen 会拦截，需手动绕过 |
| macOS | ❌ | 延后到 Phase 3（需 Apple 开发者账号 + 公证） |
| 自动更新 | ❌ | 老人需手动下载新版本 |
| EXE 体积 | ~80-150MB | pandas/numpy/scipy/uvicorn/Vue 全包 |

Phase 2 计划：购买 OV/EV 代码签名证书，在 GitHub Actions 中签名 EXE，
消除 SmartScreen 提示。

Phase 3 计划：macOS 构建 + Apple 公证。
