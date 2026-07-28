# 静态网站英文版生成工具

这是一个可复制到其他静态网站项目中使用的 Node.js CLI。它通过**网易有道智云文本翻译 API（V3 签名）**，从中文 HTML 生成对应的英文 HTML 页面。

## 它会做什么

- 递归扫描源目录中的 `.html` 文件；
- 翻译静态可见中文文本，以及 `title`、`alt`、`placeholder`、`aria-label` 属性；
- 生成与源页面相同的页面层级到输出目录，例如 `index.html` → `en/index.html`；
- 自动把输出页面内的静态资源路径重新计算为指向源站已有的 `css`、`js`、`img`、`font` 等目录，因此**不会复制 CSS、普通 JS、图片或字体**；
- 会为 `components/**/*.js` 生成英文副本到 `en/components/`，并把英文页面的组件引用指向这些副本；原中文组件保持不变。
- 使用 `.translation-cache.json` 缓存已翻译内容；每条成功译文会立即写入缓存，失败后重新运行可续跑，避免重复消耗 API 配额；
- 将输出页面的 `<html lang>` 调整为 `en`。

## 它刻意不做什么

以下内容会被保护、跳过：

- HTML 页面内的 `script`、`style`、`template` 内容和 HTML 注释；
- Vue 插值和指令，例如 `{{ item.title }}`、`v-if`、`v-for`、`:href`、`@click`；
- `jsonDatas/` 目录；
- JavaScript / JSON 数据中的动态文案。

组件是唯一的例外：工具会处理 `components/**/*.js` 中 `template: \`...\`` 的**静态可见 HTML 文案**、无绑定的文本属性（如 `aria-label`），以及 `props` 的 `default: '中文文案'`。插值前后的静态部分也会翻译，例如 `备案号：{{siteInfo.company_keep}}` 会保留插值、只翻译“备案号：”。

组件逻辑、普通 JS 字符串、注释和动态 `jsonDatas` 数据都不会翻译；例如导航 ID 映射中的中文键会原样保留，避免破坏运行逻辑。

所以当前生成的是**页面壳层 + 组件静态文案的英文版**。来自 `jsonDatas` 的运行时数据会保持现状，后续可以另行增加 JSON 翻译模块。

## 前置条件

- Node.js 18 或更高版本（本项目已验证 Node.js 可以运行）；
- 已在网易有道智云控制台创建文本翻译应用，并获得 `APP_KEY`（应用 ID）和 `APP_SECRET`（应用密钥）。

## 在当前项目中运行

在 `html` 目录打开 PowerShell，依次执行：

```powershell
# 1) 确认 Node.js 可用
node -v

# 2) 复制私密配置模板（只需要首次执行）
Copy-Item .\tools\site-translator\youdao.config.example.json `
  .\tools\site-translator\youdao.config.json

# 3) 用编辑器打开并填写 appKey / appSecret
notepad .\tools\site-translator\youdao.config.json

# 4) 保持默认限流配置：每 600ms 最多请求一次；收到 411 会自动退避重试
#    requestIntervalMs / maxRetries / retryBaseDelayMs 可按需要调整。

# 5) 先只扫描：不调用 API、不创建 en 目录
node .\tools\site-translator\translate-site.mjs `
  --source . `
  --output .\en `
  --config .\tools\site-translator\youdao.config.json `
  --dry-run

# 6) 正式生成英文页面
node .\tools\site-translator\translate-site.mjs `
  --source . `
  --output .\en `
  --config .\tools\site-translator\youdao.config.json
```

生成后可以从项目根目录启动一个本地静态服务：

```powershell
python -m http.server 8080
```

然后访问：`http://localhost:8080/en/`

> 不建议直接双击 `en/index.html` 使用 `file://` 打开。项目可能依赖 AJAX 或其他浏览器安全策略；本地 HTTP 服务更接近实际部署环境。

## 其他项目复用

将整个 `tools/site-translator/` 目录复制到另一个静态站项目，并在该项目根目录按以下格式执行：

```powershell
node .\tools\site-translator\translate-site.mjs `
  --source . `
  --output .\en `
  --config .\tools\site-translator\youdao.config.json
```

约定保持不变：输出目录放在源目录之下时，工具会自动跳过该输出目录，避免把已生成英文页面再当作源文件翻译。

## 请求限流与 411 重试

默认配置已针对批量翻译设置为：每次请求至少间隔 `600ms`。如果有道返回 `errorCode=411`，工具会按 `1s → 2s → 4s → 8s` 自动退避重试，最多重试 4 次。

可在 `youdao.config.json` 调整以下数字配置：

```json
{
  "requestIntervalMs": 600,
  "maxRetries": 4,
  "retryBaseDelayMs": 1000
}
```

如果仍持续出现 `411`，请将 `requestIntervalMs` 增大到 `1000` 或更高，并检查有道后台的应用配额与 QPS 限制。

## 常用参数

```text
--dry-run   仅扫描与统计；适合首次运行前确认范围。
--force     忽略翻译缓存并重新请求 API；通常不需要。
--help      查看命令帮助。
```

## 安全与提交建议

`youdao.config.json` 包含真实 API 密钥，已经通过项目 `.gitignore` 忽略，**不要提交到 Git**。

`.translation-cache.json` 不含密钥，但记录了调用过的源文本与译文；默认也被忽略。若团队希望统一共享译文缓存，可经过审查后再决定是否提交。

英文输出目录 `en/` 默认不会被忽略，便于把生成后的英文站一起提交和部署；其中 `en/components/` 是自动生成的英文组件副本，也应随英文站一并部署。如果只希望本地预览，可以自行在 `.gitignore` 添加 `en/`。

