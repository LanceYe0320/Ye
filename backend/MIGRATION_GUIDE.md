# YE 安装与迁移教程（保姆级）

> 全中文手把手教程，照着做就行。把 YE 搬到任何电脑上都能跑。

---

## 一、你需要准备什么

- 一台电脑（Windows / Mac / Linux 都行）
- 能上网（需要访问 open.bigmodel.cn）
- 一个智谱 AI 的 API Key（免费注册就能拿到）

---

## 二、申请智谱 API Key（免费）

1. 打开浏览器，访问 **https://open.bigmodel.cn/**
2. 点「注册」，用手机号注册一个账号
3. 登录后，点右上角头像 →「API Keys」
4. 点「创建 API Key」
5. 复制生成的 Key（长这样：`abc123.def456.xxx`），保存到记事本

> 新用户注册会送免费额度，够用很久，不用担心扣钱。

---

## 三、安装 Python

### Windows

1. 打开 **https://www.python.org/downloads/**
2. 下载 Python 3.12（点那个黄色大按钮）
3. 双击安装包
4. **最重要的一步：勾选底部的「Add Python to PATH」**
5. 点「Install Now」
6. 装完后打开命令提示符（Win+R → 输入 cmd → 回车），输入：
   ```
   python --version
   ```
   看到 `Python 3.12.x` 就说明装好了

### Mac

打开终端，输入：
```bash
brew install python@3.12
```

### Linux（Ubuntu/Debian）

```bash
sudo apt update && sudo apt install python3.12 python3.12-venv
```

---

## 四、把 YE 拷贝到目标电脑

### 方法一：U盘（最简单）

1. 在当前电脑上，找到 `backend` 文件夹
2. 整个复制到 U 盘
3. 到新电脑上，把 `backend` 粘贴到目标位置，比如 `D:\ye\`

### 方法二：通过飞书/企业微信/网盘

1. 把 `backend` 文件夹打成 zip 压缩包
2. 发送到新电脑
3. 解压到目标位置

### 方法三：Git（如果你有公司 Git）

```bash
git clone <你的仓库地址>
```

> 最终你在新电脑上有这样的目录结构：
> ```
> D:\ye\backend\
>   ├── app\          ← 程序代码
>   ├── pyproject.toml ← 依赖配置
>   └── install.ps1   ← 安装脚本
> ```

---

## 五、一键安装 YE

### Windows（推荐用安装脚本）

1. 按 `Win+R`，输入 `powershell`，回车
2. 进入 backend 目录：
   ```powershell
   cd D:\ye\backend
   ```
3. 运行安装脚本：
   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
4. 它会提示你输入 API Key，粘贴进去按回车
5. 等它装完（大概1-2分钟），看到绿色的成功提示就行了

### Windows（手动安装）

如果安装脚本报错，可以手动装：

```powershell
cd D:\ye\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

然后手动创建 `.env` 文件（见下一节）。

### Mac / Linux

打开终端：

```bash
cd ~/ye/backend
bash install.sh
```

或者手动：

```bash
cd ~/ye/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 六、配置 API Key（如果安装脚本里没填）

在 `backend` 目录下，新建一个文件叫 `.env`（注意前面有个点），内容只写一行：

```
ZHIPU_API_KEY=你之前复制的Key粘贴在这里
```

例如：
```
ZHIPU_API_KEY=abc123.def456.xxx
```

> Windows 创建 `.env` 文件的方法：
> 1. 右键 → 新建 → 文本文档
> 2. 重命名为 `.env`（文件名就是 `.env`，没有前缀）
> 3. 如果 Windows 不让你起这个名字，先叫 `1.env`，然后在命令行里 `ren 1.env .env`

---

## 七、启动使用

### Windows

```powershell
cd D:\ye\backend
.\.venv\Scripts\Activate.ps1
ye
```

### Mac / Linux

```bash
cd ~/ye/backend
source .venv/bin/activate
ye
```

启动后你会看到 YE 的 logo 和 `>` 提示符，直接打字就能对话。

### 单次提问（不用进交互模式）

```bash
ye -p "解释一下 Python 装饰器"
```

### 常用命令

在交互模式里，输入 `/` 开头的命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/doctor` | 检查 API 是否连通（推荐第一次用先跑这个） |
| `/status` | 查看当前会话信息 |
| `/model` | 查看或切换模型 |
| `/cost` | 查看花了多少 token |
| `/clear` | 清空对话记录 |
| `/exit` | 退出 |

### 第一次使用建议

1. 启动 ye
2. 输入 `/doctor`，看到 `API: connected` 说明一切正常
3. 输入 `你好`，看 YE 是否能正常回复
4. 然后就可以正常使用了

---

## 八、常见问题

### 问：输入 `python` 提示找不到命令

Windows 上试试 `py` 或 `python3`。如果都不行，说明 Python 没装好或没加 PATH，重新装一遍，记得勾选「Add to PATH」。

### 问：输入 `ye` 提示找不到命令

你需要先激活虚拟环境：

```powershell
# Windows
cd D:\ye\backend
.\.venv\Scripts\Activate.ps1
ye

# Mac/Linux
cd ~/ye/backend
source .venv/bin/activate
ye
```

### 问：API 连接失败

1. 打开 ye，输入 `/doctor`
2. 看 `API:` 那行是不是 `connected`
3. 如果显示 `connection failed`：
   - 检查 `.env` 文件里的 Key 是否正确
   - 确认电脑能上网
   - 确认能访问 open.bigmodel.cn（公司内网可能有限制）

### 问：公司需要代理才能上网

在 `.env` 文件里加一行：

```
HTTPS_PROXY=http://proxy.company.com:8080
```

### 问：执行危险操作时 YE 会问我确认

这是安全机制。YE 在执行写文件、编辑文件、运行命令之前会问你「允许执行? [y/N]」：
- 输入 `y` 允许
- 直接回车或输入 `n` 拒绝

### 问：如何创建桌面快捷方式

Windows 上可以创建一个 `.bat` 文件放在桌面：

```bat
@echo off
cd /d D:\ye\backend
call .venv\Scripts\activate.bat
ye
```

双击就能启动 YE。

---

## 九、快速迁移清单

打印出来，搬到新电脑照着打勾：

```
□ 1. 注册 open.bigmodel.cn，拿到 API Key
□ 2. 安装 Python 3.12（Windows 记得勾 Add to PATH）
□ 3. 把 backend 文件夹拷到新电脑
□ 4. 打开终端，cd 到 backend 目录
□ 5. 运行安装脚本（Windows: install.ps1 / Mac: install.sh）
□ 6. 输入 API Key
□ 7. 启动 ye
□ 8. 输入 /doctor，确认 API connected
□ 9. 开始用！
```

---

## 十、文件结构参考

```
backend/
├── app/               ← 程序代码（不用动）
│   ├── cli/           ← 命令行界面
│   ├── llm/           ← AI 模型调用
│   ├── llm/tools/     ← 工具（读写文件、搜索等）
│   └── ...
├── .venv/             ← 虚拟环境（自动生成，不用管）
├── .env               ← 你的 API Key 配置
├── data/              ← 数据存储（自动生成）
├── pyproject.toml     ← 依赖配置（不用动）
├── install.ps1        ← Windows 安装脚本
├── install.sh         ← Mac/Linux 安装脚本
├── Dockerfile         ← Docker 部署（可选）
└── docker-compose.yml ← Docker 编排（可选）
```

你只需要拷贝 `backend/` 文件夹，其他都不用管。
