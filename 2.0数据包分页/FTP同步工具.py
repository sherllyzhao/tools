# -*- coding: utf-8 -*-
"""
FTP 内容同步工具 - 一体化版本
集成配置、诊断、密码、同步所有功能
"""

import json
import os
import sys
import shutil
import math
import io
import zipfile
import struct
import urllib.request
import urllib.error
from datetime import datetime
from ftplib import FTP

# 建站通导出接口：返回 jsonDatas.zip，比 FTP 更快拿到最新数据
DEFAULT_API_BASE_URL = "https://jzt2.china9.cn/api/Download/index"

# --- 编码兜底：确保在 Windows GBK 控制台/重定向下也能输出 emoji 与中文，不崩溃 ---
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
# ---------------------------------------------------------------------------


class FTPToolkit:
    def __init__(self):
        # 程序所在目录（exe 打包 / 脚本运行都能正确定位）
        if getattr(sys, "frozen", False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # 全局设置文件，始终放在程序旁边，记录用户选择的工作目录
        self.settings_file = os.path.join(self.base_dir, "settings.json")

        # 工作目录：优先读设置文件，否则默认程序所在目录
        self.work_dir = self.load_work_dir()
        self.configs_dir = os.path.join(self.work_dir, "ftp_configs")
        os.makedirs(self.configs_dir, exist_ok=True)

    def load_work_dir(self):
        """读取工作目录设置，无有效设置则返回程序所在目录。"""
        try:
            if os.path.isfile(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                wd = s.get("work_dir", "").strip()
                if wd and os.path.isdir(wd):
                    return wd
        except:
            pass
        return self.base_dir

    def save_work_dir(self, path):
        """保存工作目录设置。"""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump({"work_dir": path}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[错误] 保存设置失败: {e}")
            return False

    def notify_sync_complete(self, config_name):
        """同步完成后：系统通知 + 打开企业微信对话窗口"""
        msg = f"✅ {config_name} FTP 同步完成"

        # 方式 1：Windows 系统通知（用 PowerShell）
        try:
            import subprocess
            ps_cmd = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
    <visual>
        <binding template="ToastText02">
            <text id="1">FTP 同步工具</text>
            <text id="2">{msg}</text>
        </binding>
    </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("FTP同步工具").Show($toast)
'''
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=3)
        except Exception:
            # 降级：简单的消息框
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                from tkinter import messagebox
                messagebox.showinfo("FTP 同步工具", msg)
                root.destroy()
            except Exception:
                print(f"\n[通知] {msg}")

        # 方式 2：打开企业微信对话窗口
        username = self.load_setting("weixin_username", "车永明")
        try:
            # 企业微信 URL scheme：wxwork://message/?username=xxx
            weixin_url = f"wxwork://message/?username={username}"
            os.startfile(weixin_url)
        except Exception as e:
            print(f"[提示] 无法打开企业微信: {e}")
            print(f"[提示] 请手动打开企业微信，给 {username} 发消息：{config_name} 已更新")

    def load_setting(self, key, default=""):
        """从 settings.json 读取设置值"""
        try:
            if os.path.isfile(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                return s.get(key, default)
        except:
            pass
        return default

    def save_setting(self, key, value):
        """保存设置到 settings.json"""
        try:
            data = {}
            if os.path.isfile(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[key] = value
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[错误] 保存设置失败: {e}")
            return False

    def set_weixin_username(self):
        """菜单：设置企业微信账号（用于同步完成后通知）"""
        print("\n" + "=" * 70)
        print("设置企业微信账号".center(70))
        print("=" * 70)

        current = self.load_setting("weixin_username", "车永明")
        print(f"\n当前账号: {current}")
        new_username = input("请输入新的账号 (直接回车保持不变): ").strip()

        if new_username:
            if self.save_setting("weixin_username", new_username):
                print(f"✅ 已设置为: {new_username}")
        else:
            print("已取消")

    def set_work_dir(self):
        """菜单：设置工作目录（配置和分页产物的存放位置）。"""
        print("\n" + "=" * 70)
        print("设置工作目录".center(70))
        print("=" * 70)
        print(f"\n当前工作目录: {self.work_dir}")
        print("（配置文件 ftp_configs 就存放在这里）\n")
        new_dir = input("请输入新的工作目录 (直接回车取消): ").strip().strip('"')
        if not new_dir:
            print("已取消")
            return
        if not os.path.isdir(new_dir):
            if input("目录不存在，是否创建？(y/n): ").strip().lower() == "y":
                try:
                    os.makedirs(new_dir, exist_ok=True)
                except Exception as e:
                    print(f"[错误] 创建失败: {e}")
                    return
            else:
                print("已取消")
                return
        if self.save_work_dir(new_dir):
            self.work_dir = new_dir
            self.configs_dir = os.path.join(new_dir, "ftp_configs")
            os.makedirs(self.configs_dir, exist_ok=True)
            print(f"✅ 工作目录已设置为: {new_dir}")

    def clear_screen(self):
        """清屏"""
        os.system("cls" if os.name == "nt" else "clear")

    def show_menu(self):
        """主菜单"""
        self.clear_screen()
        print("=" * 70)
        print("FTP 内容同步工具 - 一体化版本".center(70))
        print("=" * 70)
        print(f"\n工作目录: {self.work_dir}")
        print("\n请选择功能：\n")
        print("  1. 执行同步 / 分页 (流程由配置的运行模式决定)")
        print("  2. 诊断 FTP 连接")
        print("  3. 管理 FTP 密码")
        print("  4. 管理配置文件")
        print("  5. 查看配置详情")
        print("  6. 设置工作目录 (配置/产物存放位置)")
        print("  7. 设置企业微信账号 (同步完成后通知)")
        print("  0. 退出")
        print("\n" + "-" * 70)

        try:
            choice = input("请选择 (0-7): ").strip()
            return choice
        except:
            return "0"

    def list_configs(self):
        """列出所有配置"""
        configs = []
        if os.path.isdir(self.configs_dir):
            for f in os.listdir(self.configs_dir):
                if f.endswith(".json"):
                    configs.append(f[:-5])
        return sorted(configs)

    def load_config(self, name):
        """加载配置"""
        config_file = os.path.join(self.configs_dir, f"{name}.json")
        if not os.path.isfile(config_file):
            return None
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return self.normalize_config(json.load(f))
        except:
            return None

    def save_config(self, name, config):
        """保存配置"""
        config_file = os.path.join(self.configs_dir, f"{name}.json")
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except:
            return False

    def select_config(self):
        """选择或创建配置"""
        configs = self.list_configs()

        print("\n已保存的配置：\n")
        for i, name in enumerate(configs, 1):
            cfg = self.load_config(name)
            if cfg:
                print(f"  {i}. {name} (FTP: {cfg.get('ftp_host', '?')})")

        print(f"  {len(configs) + 1}. 新建配置")
        print(f"  0. 返回\n")

        try:
            choice = int(input("请选择: ").strip())
            if choice == 0:
                return None
            elif 1 <= choice <= len(configs):
                return configs[choice - 1]
            elif choice == len(configs) + 1:
                return self.create_config()
        except:
            pass
        return None

    @staticmethod
    def parse_ftp_block(lines):
        """解析 FlashFXP 粘贴的多行文本，返回 {host, user, pass}。

        兼容全角/半角冒号，行标签含「地址/账户/用户/密码」等关键字即可。
        """
        result = {"ftp_host": "", "ftp_user": "", "ftp_pass": ""}
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            # 统一全角冒号为半角，再按第一个冒号切分
            norm = line.replace("：", ":")
            if ":" not in norm:
                continue
            label, value = norm.split(":", 1)
            value = value.strip()
            if not value:
                continue
            # 非根目录行要先判断，避免被「地址」等误匹配
            if "非根目录" in label or "根目录" in label:
                continue
            if "地址" in label or "host" in label.lower() or "ip" in label.lower():
                result["ftp_host"] = value
            elif "账户" in label or "帐户" in label or "用户" in label or "user" in label.lower():
                result["ftp_user"] = value
            elif "密码" in label or "pass" in label.lower():
                result["ftp_pass"] = value
        return result

    @staticmethod
    def parse_paginate_files(raw):
        """把用户输入的文件列表字符串解析成规范化的文件名数组。

        - 支持中英文逗号、分号、空格、换行分隔
        - 自动补 .json 后缀
        - 去重且保持输入顺序
        - 空输入回退到默认 ["content.json"]
        """
        if not raw or not raw.strip():
            return ["content.json"]

        normalized = raw
        for sep in ("，", "、", ";", "；", "\n", "\t", " "):
            normalized = normalized.replace(sep, ",")

        files = []
        for item in normalized.split(","):
            name = item.strip().strip("/").strip("\\")
            if not name:
                continue
            if not name.lower().endswith(".json"):
                name += ".json"
            if name not in files:
                files.append(name)

        return files or ["content.json"]

    @staticmethod
    def is_generated_json(name):
        """判断是否为本工具生成的产物 / 临时文件，这类不该当作分页源。"""
        lower = name.lower()
        return (
            "_category_statistics" in lower  # 含手工改名的变体，如 "xx_category_statistics old.json"
            or lower.startswith(".temp_")
            or lower.startswith("~")
        )

    @staticmethod
    def fetch_remote_json_files(config):
        """列出远程上传目录下「一级」的 .json 文件名。

        优先用 MLSD（能明确区分文件与目录），服务器不支持时退回 NLST
        并按 .json 后缀过滤。不递归子目录。

        返回文件名列表；连接或列目录失败返回 None，便于调用方降级为手输。
        """
        remote_dir = (config.get("ftp_upload_path") or "/jsonDatas").rstrip("/") or "/"
        ftp = None
        try:
            print(f"\n[FTP] 连接 {config['ftp_host']} 读取 {remote_dir} ...")
            ftp = FTP(config["ftp_host"], timeout=30)
            ftp.login(config["ftp_user"], config["ftp_pass"])
            ftp.set_pasv(True)
            ftp.cwd(remote_dir)

            names = []
            # 首选 MLSD：facts 里带 type，能可靠排除目录
            try:
                for name, facts in ftp.mlsd():
                    if facts.get("type") != "file":
                        continue
                    if name.lower().endswith(".json"):
                        names.append(name)
            except Exception:
                # 老服务器不支持 MLSD，退回 NLST
                names = []
                for entry in ftp.nlst():
                    # NLST 可能返回带路径的项，只取最后一段
                    name = entry.replace("\\", "/").rstrip("/").split("/")[-1]
                    if name.lower().endswith(".json"):
                        names.append(name)

            files = sorted({n for n in names if not FTPToolkit.is_generated_json(n)})
            print(f"[FTP] 找到 {len(files)} 个可分页的 json 文件")
            return files
        except Exception as e:
            print(f"[错误] 读取远程目录失败: {e}")
            return None
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    try:
                        ftp.close()
                    except:
                        pass

    @staticmethod
    def truncate_to_zip(data):
        """截掉 ZIP 之后的附加内容。

        建站通接口开着 ThinkPHP 调试模式，会把几十 KB 的 trace 面板 HTML
        直接拼在 zip 二进制后面。按 EOCD（中央目录结束记录）定位真实结尾，
        否则 zipfile 会因尾部垃圾数据报错或警告。
        """
        if not data.startswith(b"PK"):
            return data
        end = data.rfind(b"PK\x05\x06")
        if end == -1 or end + 22 > len(data):
            return data
        try:
            comment_len = struct.unpack("<H", data[end + 20 : end + 22])[0]
        except struct.error:
            return data
        return data[: end + 22 + comment_len]

    @staticmethod
    def download_api_zip(config):
        """从建站通接口下载 jsonDatas.zip，返回 zipfile.ZipFile。

        失败时打印原因并返回 None，让调用方决定降级还是中止。
        """
        site_id = (config.get("site_id") or "").strip()
        if not site_id:
            print("[错误] 未设置 site_id，无法从接口下载")
            print("       请到 配置管理 → 运行模式 里填写")
            return None

        base = (config.get("api_base_url") or DEFAULT_API_BASE_URL).strip()
        sep = "&" if "?" in base else "?"
        url = f"{base}{sep}site_id={site_id}"

        try:
            print(f"\n[接口] 下载 {base} (site_id={site_id}) ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            print(f"[错误] 接口返回 HTTP {e.code}")
            return None
        except Exception as e:
            print(f"[错误] 接口请求失败: {e}")
            return None

        if not raw:
            print("[错误] 接口返回空内容")
            return None

        data = FTPToolkit.truncate_to_zip(raw)
        if len(data) != len(raw):
            print(f"[接口] 收到 {len(raw)} 字节，剥离尾部调试内容后 {len(data)} 字节")
        else:
            print(f"[接口] 收到 {len(raw)} 字节")

        if not data.startswith(b"PK"):
            # 多半是网关错误页或鉴权失败页，给出可读的前几行帮助排查
            head = raw[:200].decode("utf-8", "replace").replace("\n", " ")
            print(f"[错误] 返回的不是 zip 文件，开头内容: {head}")
            return None

        try:
            return zipfile.ZipFile(io.BytesIO(data))
        except Exception as e:
            print(f"[错误] zip 解析失败: {e}")
            return None

    @staticmethod
    def list_zip_json_files(zf):
        """列出 zip 里「一级」的 json 文件名（不含子目录、不含工具产物）。

        接口的包结构是 jsonDatas/xxx.json，另有 content/、goods/ 等子目录
        存详情页数据。分页只针对一级列表文件，子目录一律忽略。
        """
        names = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = info.filename.replace("\\", "/")
            parts = [p for p in path.split("/") if p]
            if not parts:
                continue
            # 去掉最外层 jsonDatas/ 目录后，剩余层级 >1 说明在子目录里
            if parts[0].lower() == "jsondatas":
                parts = parts[1:]
            if len(parts) != 1:
                continue
            name = parts[0]
            if not name.lower().endswith(".json"):
                continue
            if FTPToolkit.is_generated_json(name):
                continue
            names.append(name)
        return sorted(set(names))

    @staticmethod
    def read_zip_json(zf, filename):
        """从 zip 里按文件名取内容，兼容有无 jsonDatas/ 前缀两种写法。

        返回 bytes；找不到返回 None。
        """
        target = filename.replace("\\", "/").strip("/").lower()
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = info.filename.replace("\\", "/").strip("/")
            low = path.lower()
            if low == target or low.endswith("/" + target):
                return zf.read(info.filename)
        return None

    @staticmethod
    def fetch_api_json_files(config):
        """列出接口 zip 里可分页的 json 文件名。

        与 fetch_remote_json_files 同契约：成功返回列表，失败返回 None。
        """
        zf = FTPToolkit.download_api_zip(config)
        if zf is None:
            return None
        try:
            files = FTPToolkit.list_zip_json_files(zf)
            print(f"[接口] 找到 {len(files)} 个可分页的 json 文件")
            return files
        finally:
            try:
                zf.close()
            except Exception:
                pass

    @staticmethod
    def fetch_local_json_files(config):
        """列出本地基础目录下「一级」的 .json 文件名。

        与 fetch_remote_json_files 同契约：成功返回文件名列表，
        目录不存在或读取失败返回 None，便于调用方降级为手输。
        """
        local_dir = config.get("local_base_dir") or ""
        if not local_dir or not os.path.isdir(local_dir):
            print(f"\n[错误] 本地目录不存在: {local_dir or '(未设置)'}")
            return None

        try:
            print(f"\n[本地] 读取 {local_dir} ...")
            names = [
                n
                for n in os.listdir(local_dir)
                if n.lower().endswith(".json")
                and os.path.isfile(os.path.join(local_dir, n))
                and not FTPToolkit.is_generated_json(n)
            ]
            files = sorted(set(names))
            print(f"[本地] 找到 {len(files)} 个可分页的 json 文件")
            return files
        except Exception as e:
            print(f"[错误] 读取本地目录失败: {e}")
            return None

    @staticmethod
    def normalize_config(config):
        """补齐旧配置缺失的字段，保证老配置无缝可用。"""
        if not isinstance(config, dict):
            return config

        # 旧配置只有 ftp_source_path（单文件），迁移成 paginate_files 列表
        if not config.get("paginate_files"):
            legacy = config.get("ftp_source_path", "")
            legacy_name = os.path.basename(legacy).strip() if legacy else ""
            config["paginate_files"] = [legacy_name] if legacy_name else ["content.json"]

        if not config.get("ftp_upload_path"):
            config["ftp_upload_path"] = "/jsonDatas"

        if not isinstance(config.get("page_size"), int) or config["page_size"] <= 0:
            config["page_size"] = 20

        # 数据源：http = 接口下载 zip（推荐，最快拿到最新）
        #        ftp  = 从 FTP 下载（可能滞后）
        #        local = 直接用本地已有的
        if config.get("source_mode") not in ("ftp", "local", "http"):
            config["source_mode"] = "ftp"

        # 接口下载相关：站点 id 由用户填写，接口地址一般不用改
        if not config.get("api_base_url"):
            config["api_base_url"] = DEFAULT_API_BASE_URL
        if "site_id" not in config:
            config["site_id"] = ""

        # 分页完是否回传服务器；关掉就是「只分页，产物留本地」
        if not isinstance(config.get("upload_after_paginate"), bool):
            config["upload_after_paginate"] = True

        return config

    @staticmethod
    def resolve_selection(raw, available):
        """把用户输入解析成文件名列表。

        支持三种写法（可混用逗号分隔）：
          - 序号：1,3,5      → 取 available 里对应项
          - all / a / *      → 全选
          - 文件名：news.json → 直接按名字（自动补 .json）

        无法识别的项忽略。返回去重保序的列表；无有效项返回 []。
        """
        if not raw or not raw.strip():
            return []

        text = raw.strip()
        if text.lower() in ("all", "a", "*"):
            return list(available)

        normalized = text
        for sep in ("，", "、", ";", "；", "\n", "\t", " "):
            normalized = normalized.replace(sep, ",")

        picked = []
        for item in normalized.split(","):
            token = item.strip()
            if not token:
                continue
            if token.isdigit():
                idx = int(token)
                if 1 <= idx <= len(available):
                    name = available[idx - 1]
                else:
                    print(f"  [跳过] 序号 {idx} 超出范围")
                    continue
            else:
                name = token.strip("/").strip("\\")
                if not name.lower().endswith(".json"):
                    name += ".json"
            if name not in picked:
                picked.append(name)
        return picked

    def choose_paginate_files(self, config, current=None):
        """交互式选择需要分页的文件。

        默认单文件（content.json）；用户确认需要多文件时，才按当前数据源
        （接口/FTP 远程 / 本地目录）拉取一级 json 列表供勾选。
        返回文件名列表；用户取消时返回 None（调用方保持原值不变）。
        """
        current = current or ["content.json"]
        mode = config.get("source_mode", "ftp")
        where_map = {"http": "接口", "ftp": "远程", "local": "本地"}
        where = where_map.get(mode, "未知源")

        print("\n" + "=" * 70)
        print("分页文件设置".center(70))
        print("=" * 70)
        print(f"当前分页文件: {', '.join(current)}")
        answer = input("\n是否需要多文件分页？(y/N，默认 N 只分页 content.json): ").strip().lower()

        if answer not in ("y", "yes", "是"):
            print("  → 使用默认: content.json")
            return ["content.json"]

        if mode == "http":
            available = FTPToolkit.fetch_api_json_files(config)
        elif mode == "ftp":
            available = self.fetch_remote_json_files(config)
        else:
            available = self.fetch_local_json_files(config)

        if available is None:
            # 读不到就降级为纯手输，不阻断配置流程
            print(f"\n无法读取{where}列表，请手动输入文件名（逗号分隔）")
            manual = input("文件列表 (回车取消): ").strip()
            return self.parse_paginate_files(manual) if manual else None

        if not available:
            print(f"\n⚠️  {where}没有找到可分页的 json 文件")
            manual = input("手动输入文件名 (逗号分隔，回车取消): ").strip()
            return self.parse_paginate_files(manual) if manual else None

        print(f"\n{where} json 文件：\n")
        for i, name in enumerate(available, 1):
            mark = " ← 当前已选" if name in current else ""
            print(f"  {i}. {name}{mark}")

        print("\n输入方式：序号 1,3,5 ｜ all 全选 ｜ 直接写文件名 ｜ 回车保持不变")
        raw = input("请选择: ").strip()

        if not raw:
            print(f"  → 保持不变: {', '.join(current)}")
            return None

        picked = self.resolve_selection(raw, available)
        if not picked:
            print("  ⚠️  没有识别到有效选择，保持不变")
            return None

        # 提示选了远程列表里不存在的名字（可能拼错），但不阻止
        unknown = [n for n in picked if n not in available]
        if unknown:
            print(f"  ⚠️  以下文件不在{where}列表中: {', '.join(unknown)}")
            if input("  仍然使用？(y/N): ").strip().lower() not in ("y", "yes", "是"):
                picked = [n for n in picked if n in available]
                if not picked:
                    print("  → 已全部移除，保持不变")
                    return None

        print(f"  → 将分页 {len(picked)} 个文件: {', '.join(picked)}")
        return picked

    def create_config(self):
        """创建新配置 - 支持整块粘贴，远程 jsonDatas 固定在根目录"""
        print("\n" + "=" * 70)
        print("新建 FTP 配置".center(70))
        print("=" * 70)
        print("\n请把 FTP 信息整块粘贴进来（4 行），格式如下：")
        print("-" * 70)
        print("FTP地址:222.171.249.195")
        print("FTP非根目录:")
        print("FTP账户:hrbls_org")
        print("FTP密码:X7FEzMhJbSPh4jZJ")
        print("-" * 70)
        print("粘贴后按回车；若某行漏了，输入空行结束录入。\n")

        # 逐行读取，凑齐 host+user+pass 即停；最多读 8 行防呆
        lines = []
        for _ in range(8):
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "" and lines:
                break  # 空行且已有内容 -> 结束
            lines.append(line)
            parsed_now = self.parse_ftp_block(lines)
            if parsed_now["ftp_host"] and parsed_now["ftp_user"] and parsed_now["ftp_pass"]:
                break

        parsed = self.parse_ftp_block(lines)

        # 缺项则单独补问
        if not parsed["ftp_host"]:
            parsed["ftp_host"] = input("FTP 地址: ").strip()
        if not parsed["ftp_user"]:
            parsed["ftp_user"] = input("FTP 账户: ").strip()
        if not parsed["ftp_pass"]:
            parsed["ftp_pass"] = input("FTP 密码: ").strip()

        config = {
            "ftp_host": parsed["ftp_host"],
            "ftp_user": parsed["ftp_user"],
            "ftp_pass": parsed["ftp_pass"],
            # 远程 jsonDatas 固定在根目录，无需每次填写
            "ftp_upload_path": "/jsonDatas",
        }

        print("\n解析结果：")
        print(f"  FTP 地址: {config['ftp_host']}")
        print(f"  FTP 账户: {config['ftp_user']}")
        print(f"  FTP 密码: {config['ftp_pass']}")
        print(f"  上传目录: {config['ftp_upload_path']} (固定)")

        # 本地目录因项目而异，仍需询问
        config["local_base_dir"] = input("\n本地基础目录 (分页文件存这里): ").strip()
        page_size_str = input("每页条数 (默认 20): ").strip()
        config["page_size"] = int(page_size_str) if page_size_str.isdigit() else 20

        # 需要分页的文件（默认 content.json，可选多文件并从 FTP 拉取列表）
        chosen = self.choose_paginate_files(config)
        config["paginate_files"] = chosen or ["content.json"]

        config_name = input("\n配置名称 (用于保存): ").strip()
        if config_name and self.save_config(config_name, config):
            print(f"✅ 配置已保存: {config_name}")
            return config_name
        return None

    def diagnose_ftp(self, config_name):
        """诊断 FTP 连接"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print("\n" + "=" * 70)
        print(f"FTP 诊断 - {config_name}".center(70))
        print("=" * 70 + "\n")

        print(f"FTP 主机: {config['ftp_host']}")
        print(f"账户: {config['ftp_user']}")
        print("-" * 70)

        # 测试 TCP
        print("\n[1/5] TCP 连接...")
        try:
            ftp = FTP(config["ftp_host"], timeout=30)
            print("✅ TCP 连接成功")
        except Exception as e:
            print(f"❌ TCP 连接失败: {e}")
            return

        # 测试登录
        print("[2/5] 认证登录...")
        try:
            ftp.login(config["ftp_user"], config["ftp_pass"])
            print("✅ 认证成功")
        except Exception as e:
            print(f"❌ 认证失败: {e}")
            ftp.quit()
            return

        # 测试被动模式
        print("[3/5] 被动模式...")
        try:
            ftp.set_pasv(True)
            print("✅ 被动模式设置成功")
        except Exception as e:
            print(f"⚠️  被动模式失败: {e}")

        # 测试目录
        print(f"[4/5] 目录访问 ({config['ftp_upload_path']})...")
        try:
            ftp.cwd(config["ftp_upload_path"])
            files = ftp.nlst()
            print(f"✅ 目录访问成功，包含 {len(files)} 个项目")
        except Exception as e:
            print(f"⚠️  目录访问失败: {e}")

        # 测试源文件
        files = config.get("paginate_files") or ["content.json"]
        upload_base = config["ftp_upload_path"].rstrip("/")
        print(f"[5/5] 检查源文件 ({len(files)} 个)...")
        for filename in files:
            remote = f"{upload_base}/{filename}"
            try:
                size = ftp.size(remote)
                print(f"  ✅ {filename} 存在，大小: {size} bytes")
            except Exception as e:
                print(f"  ⚠️  {filename} 检查失败: {e}")

        ftp.quit()
        print("\n✅ 诊断完成")

    def update_password(self, config_name):
        """更新密码"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print(f"\n配置: {config_name}")
        print(f"FTP: {config['ftp_host']}")
        print(f"当前密码: {config['ftp_pass'][:3]}{'*' * (len(config['ftp_pass']) - 3)}")

        new_pass = input("\n请输入新密码 (直接粘贴，会显示出来便于核对): ").strip()
        if not new_pass:
            print("❌ 密码不能为空")
            return

        config["ftp_pass"] = new_pass
        if self.save_config(config_name, config):
            print("✅ 密码已更新，测试连接...")

            # 自动测试
            try:
                ftp = FTP(config["ftp_host"], timeout=30)
                ftp.login(config["ftp_user"], config["ftp_pass"])
                ftp.quit()
                print("✅ 连接测试成功！")
            except Exception as e:
                print(f"❌ 连接测试失败: {e}")

    @staticmethod
    def describe_flow(config):
        """把运行模式翻译成一句人话，菜单/同步入口共用。"""
        mode = config.get("source_mode", "ftp")
        do_upload = config.get("upload_after_paginate", True)
        source_desc = {
            "http": "接口下载",
            "ftp": "FTP 下载",
            "local": "本地文件",
        }.get(mode, "未知源")
        return (
            f"{source_desc} → 分页"
            f"{' → 上传' if do_upload else '（不上传，产物留本地）'}"
        )

    def view_config(self, config_name):
        """查看配置详情"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        labels = {
            "source_mode": "数据源",
            "upload_after_paginate": "分页后上传",
            "site_id": "接口 site_id",
            "api_base_url": "接口地址",
        }
        readable = {
            "source_mode": {"http": "接口下载", "ftp": "FTP 下载", "local": "本地文件"},
            "upload_after_paginate": {True: "是", False: "否"},
        }

        print(f"\n配置: {config_name}")
        print("-" * 70)
        print(f"  运行流程: {self.describe_flow(config)}")
        print("-" * 70)
        for key, value in config.items():
            if key == "ftp_pass":
                print(f"  {key}: {value[:3]}{'*' * (len(value) - 3)}")
            elif key == "site_id":
                # http 模式时才显示 site_id
                if config.get("source_mode") == "http":
                    display = value if value else "(未设置)"
                    print(f"  {labels.get(key, key)}: {display}")
            elif key == "api_base_url":
                # http 模式时才显示接口地址
                if config.get("source_mode") == "http":
                    print(f"  {labels.get(key, key)}: {value}")
            elif key in readable:
                shown = readable[key].get(value, value)
                print(f"  {labels[key]}: {shown}")
            elif isinstance(value, list):
                print(f"  {key}: {', '.join(str(v) for v in value)}")
            else:
                print(f"  {key}: {value}")
        print("-" * 70)

    def edit_run_mode(self, config_name):
        """设置数据源与是否上传（长期生效，存进配置）。"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print("\n" + "=" * 70)
        print(f"运行模式 - {config_name}".center(70))
        print("=" * 70)
        print(f"\n当前流程: {self.describe_flow(config)}")

        print("\n数据源：")
        print("  1. FTP 下载（每次同步前拉最新的）")
        print("  2. 本地文件（直接用 local_base_dir 里已有的）")
        print("  3. 接口下载（最快拿最新数据，推荐）")
        src = input(f"请选择 (回车保持 {'1' if config.get('source_mode', 'ftp') == 'ftp' else ('2' if config.get('source_mode') == 'local' else '3')}): ").strip()

        changed = False
        if src == "1":
            changed = config.get("source_mode") != "ftp"
            config["source_mode"] = "ftp"
        elif src == "2":
            changed = config.get("source_mode") != "local"
            config["source_mode"] = "local"
        elif src == "3":
            changed = config.get("source_mode") != "http"
            config["source_mode"] = "http"
            # 如果选了接口，需要填 site_id
            if config.get("source_mode") == "http":
                current_id = (config.get("site_id") or "").strip()
                site_id = input(f"\n请输入 site_id (当前: {current_id or '未设置'}): ").strip()
                if site_id:
                    config["site_id"] = site_id
                    changed = True
                elif not current_id:
                    print("  ⚠️  未设置 site_id，接口无法使用")

        print("\n分页完是否上传到服务器？")
        print("  1. 上传（完整同步）")
        print("  2. 不上传（只分页，产物留本地）")
        up = input(f"请选择 (回车保持 {'1' if config.get('upload_after_paginate', True) else '2'}): ").strip()

        if up == "1":
            changed = changed or config.get("upload_after_paginate") is not True
            config["upload_after_paginate"] = True
        elif up == "2":
            changed = changed or config.get("upload_after_paginate") is not False
            config["upload_after_paginate"] = False

        if not changed:
            print("\n未做修改")
            return

        print(f"\n新的流程: {self.describe_flow(config)}")
        if config["source_mode"] == "local":
            print(f"本地源目录: {config.get('local_base_dir', '(未设置)')}")
        elif config["source_mode"] == "http":
            print(f"接口地址: {config.get('api_base_url', DEFAULT_API_BASE_URL)}")
            print(f"site_id: {config.get('site_id', '(未设置)')}")

        if self.save_config(config_name, config):
            print("\n✅ 运行模式已保存")

    def sync_ftp(self, config_name):
        """执行同步 / 分页（具体做什么由配置的运行模式决定）。"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        do_upload = config.get("upload_after_paginate", True)
        title = "FTP 同步" if do_upload else "仅分页"

        print("\n" + "=" * 70)
        print(f"{title} - {config_name}".center(70))
        print("=" * 70)

        current = config.get("paginate_files") or ["content.json"]
        print(f"\n运行流程: {self.describe_flow(config)}")
        print(f"当前分页文件 ({len(current)} 个): {', '.join(current)}")

        answer = input("\n回车开始，c 改分页文件，m 改运行模式: ").strip().lower()

        if answer == "c":
            chosen = self.choose_paginate_files(config, current)
            if chosen:
                config["paginate_files"] = chosen
                self.save_config(config_name, config)
                print(f"\n✅ 已保存: {', '.join(chosen)}")
        elif answer == "m":
            self.edit_run_mode(config_name)
            # 模式已落盘，重新读取以应用新设置
            config = self.load_config(config_name) or config
            print(f"\n即将执行: {self.describe_flow(config)}")
            input("按回车开始...")

        sync = FTPSync(config, toolkit=self, config_name=config_name)
        sync.run()

    def manage_config(self):
        """配置管理菜单"""
        while True:
            self.clear_screen()
            print("=" * 70)
            print("配置管理".center(70))
            print("=" * 70 + "\n")

            configs = self.list_configs()
            for i, name in enumerate(configs, 1):
                print(f"  {i}. {name}")
            print(f"  {len(configs) + 1}. 新建配置")
            print("  0. 返回\n")

            try:
                choice = int(input("请选择: ").strip())
                if choice == 0:
                    return
                elif 1 <= choice <= len(configs):
                    config_name = configs[choice - 1]
                    self.config_menu(config_name)
                elif choice == len(configs) + 1:
                    self.create_config()
            except:
                pass

            input("\n按回车继续...")

    def edit_paginate_files(self, config_name):
        """编辑某个配置的分页文件列表 / 每页条数。"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print("\n" + "=" * 70)
        print(f"分页设置 - {config_name}".center(70))
        print("=" * 70)

        current = config.get("paginate_files") or ["content.json"]
        print(f"\n当前分页文件 ({len(current)} 个):")
        for i, name in enumerate(current, 1):
            print(f"  {i}. {name}")
        print(f"\n当前每页条数: {config.get('page_size', 20)}")

        chosen = self.choose_paginate_files(config, current)
        changed = False
        if chosen is not None and chosen != current:
            config["paginate_files"] = chosen
            changed = True

        size_input = input("\n新的每页条数 (回车保持不变): ").strip()
        if size_input.isdigit() and int(size_input) > 0:
            config["page_size"] = int(size_input)
            print(f"  → 每页条数已设为: {config['page_size']}")
            changed = True

        if not changed:
            print("\n未做修改")
            return

        if self.save_config(config_name, config):
            print("\n✅ 分页设置已保存")

    def config_menu(self, config_name):
        """单个配置的菜单"""
        self.clear_screen()
        config = self.load_config(config_name) or {}
        print(f"\n配置: {config_name}")
        print(f"运行流程: {self.describe_flow(config)}\n")
        print("  1. 查看详情")
        print("  2. 更新密码")
        print("  3. 修改分页设置 (文件列表/每页条数)")
        print("  4. 运行模式 (数据源/是否上传)")
        print("  5. 删除配置")
        print("  0. 返回\n")

        try:
            choice = int(input("请选择: ").strip())
            if choice == 1:
                self.view_config(config_name)
                input("\n按回车继续...")
            elif choice == 2:
                self.update_password(config_name)
                input("\n按回车继续...")
            elif choice == 3:
                self.edit_paginate_files(config_name)
                input("\n按回车继续...")
            elif choice == 4:
                self.edit_run_mode(config_name)
                input("\n按回车继续...")
            elif choice == 5:
                if input(f"确定删除 {config_name}? (y/n): ").lower() == "y":
                    os.remove(os.path.join(self.configs_dir, f"{config_name}.json"))
                    print("✅ 已删除")
        except:
            pass

    def run(self):
        """主程序循环"""
        while True:
            choice = self.show_menu()

            if choice == "1":
                config_name = self.select_config()
                if config_name:
                    self.sync_ftp(config_name)
                input("\n按回车继续...")

            elif choice == "2":
                config_name = self.select_config()
                if config_name:
                    self.diagnose_ftp(config_name)
                input("\n按回车继续...")

            elif choice == "3":
                config_name = self.select_config()
                if config_name:
                    self.update_password(config_name)
                input("\n按回车继续...")

            elif choice == "4":
                self.manage_config()

            elif choice == "5":
                config_name = self.select_config()
                if config_name:
                    self.view_config(config_name)
                input("\n按回车继续...")

            elif choice == "6":
                self.set_work_dir()
                input("\n按回车继续...")

            elif choice == "7":
                self.set_weixin_username()
                input("\n按回车继续...")

            elif choice == "0":
                print("\n再见！")
                sys.exit(0)


class FTPSync:
    def __init__(self, config, toolkit=None, config_name=""):
        self.config = config
        self.ftp = None
        self.toolkit = toolkit
        self.config_name = config_name

    def connect_ftp(self):
        """连接到 FTP 服务器"""
        try:
            print(f"\n[FTP] 连接到 {self.config['ftp_host']}...")
            self.ftp = FTP(self.config["ftp_host"], timeout=30)
            self.ftp.login(self.config["ftp_user"], self.config["ftp_pass"])
            self.ftp.set_pasv(True)
            print(f"[FTP] 认证成功")
            return True
        except Exception as e:
            print(f"[错误] FTP 连接失败: {e}")
            return False

    def download_file(self, remote_path, local_path):
        """从 FTP 下载文件"""
        try:
            print(f"[下载] {remote_path}...")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                self.ftp.retrbinary(f"RETR {remote_path}", f.write)
            size = os.path.getsize(local_path)
            print(f"[下载] 完成 ({size} bytes)")
            return True
        except Exception as e:
            print(f"[错误] 下载失败: {e}")
            return False

    def upload_file(self, local_path, remote_path):
        """上传文件到 FTP"""
        try:
            print(f"[上传] {remote_path}...")
            with open(local_path, "rb") as f:
                self.ftp.storbinary(f"STOR {remote_path}", f)
            print(f"[上传] 完成")
            return True
        except Exception as e:
            print(f"[错误] 上传失败: {e}")
            return False

    def upload_tree(self, local_dir, remote_base):
        """递归上传目录树到 FTP"""
        try:
            for root, dirs, files in os.walk(local_dir):
                rel_path = os.path.relpath(root, local_dir)
                if rel_path == ".":
                    remote_dir = remote_base
                else:
                    remote_dir = remote_base + "/" + rel_path.replace("\\", "/")

                for file in files:
                    local_file = os.path.join(root, file)
                    remote_file = remote_dir + "/" + file
                    self.upload_file(local_file, remote_file)
            return True
        except Exception as e:
            print(f"[错误] 上传目录树失败: {e}")
            return False

    def process_content(self, source_file, stem):
        """处理内容：按 category_id 分组、分页、删除 details 字段。

        stem: 文件名主干（如 content / news），决定输出目录与文件名前缀。
        返回 (输出目录, 统计文件路径) 供上传阶段使用；失败返回 None。
        """
        print(f"\n[处理] 读取 {os.path.basename(source_file)}...")
        with open(source_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("[错误] 顶层不是数组")
            return None

        total_records = len(data)
        page_size = self.config.get("page_size", 20)
        print(f"[处理] 共 {total_records} 条记录，每页 {page_size} 条")

        groups = {}
        for rec in data:
            cid = rec.get("category_id") if isinstance(rec, dict) else None
            if not cid:
                cid = "uncategorized"
            groups.setdefault(cid, []).append(rec)

        local_base = self.config["local_base_dir"]
        out_dir = os.path.join(local_base, f"{stem}_by_category")
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        def sort_key(cid):
            return (1, "") if cid == "uncategorized" else (0, cid)

        stats = []
        total_files = 0
        for cid in sorted(groups.keys(), key=sort_key):
            recs = groups[cid]
            cat_dir = os.path.join(out_dir, cid)
            os.makedirs(cat_dir, exist_ok=True)

            page_count = math.ceil(len(recs) / page_size)
            print(f"  [{cid}] {len(recs)} 条 → {page_count} 个文件")

            for i in range(page_count):
                chunk = recs[i * page_size : (i + 1) * page_size]
                cleaned = []
                for r in chunk:
                    if isinstance(r, dict):
                        r2 = dict(r)
                        r2.pop("details", None)
                        cleaned.append(r2)
                    else:
                        cleaned.append(r)

                fn = os.path.join(cat_dir, f"{stem}_{cid}_{i + 1}.json")
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(cleaned, f, ensure_ascii=False, indent=2)

            total_files += page_count
            stats.append({
                "recordCount": len(recs),
                "fileCount": page_count,
                "categoryId": cid,
            })

        summary = {
            "totalCategories": len(stats),
            "totalRecords": total_records,
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "totalFiles": total_files,
            "categories": stats,
        }
        stat_file = os.path.join(local_base, f"{stem}_category_statistics.json")
        with open(stat_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"[完成] {stem}: {total_files} 个文件生成完毕")
        return out_dir, stat_file

    def close(self):
        """关闭 FTP 连接"""
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                self.ftp.close()

    def run(self):
        """主工作流：对配置里的每个文件依次「取源→分页→(可选)上传」。

        源可以是 http(接口)/ftp/本地 三种；上传可关闭。
        http 源一次性拉 ZIP 到内存，循环里逐个文件提取。
        """
        files = self.config.get("paginate_files") or ["content.json"]
        upload_base = self.config["ftp_upload_path"].rstrip("/")
        local_base = self.config["local_base_dir"]
        source_mode = self.config.get("source_mode", "ftp")
        do_upload = self.config.get("upload_after_paginate", True)

        from_http = source_mode == "http"
        from_ftp = source_mode == "ftp"

        title = "开始同步" if do_upload else "开始分页（不上传）"
        flow_desc = {
            "http": f"接口下载 → 分页{' → 上传' if do_upload else '（产物留在本地）'}",
            "ftp": f"FTP 下载 → 分页{' → 上传' if do_upload else '（产物留在本地）'}",
            "local": f"本地文件 → 分页{' → 上传' if do_upload else '（产物留在本地）'}",
        }
        flow = flow_desc.get(source_mode, "未知源 → 分页")

        print("\n" + "=" * 70)
        print(title.center(70))
        print("=" * 70)
        print(f"\n流程: {flow}")
        print(f"待处理文件 ({len(files)} 个): {', '.join(files)}")

        # 接口源：开跑前一次性拉 ZIP
        http_zip = None
        if from_http:
            http_zip = FTPToolkit.download_api_zip(self.config)
            if http_zip is None:
                return False
        elif source_mode == "local":
            print(f"本地源目录: {local_base}")

        # 只有真正需要时才连 FTP（上传或 FTP 源）
        if (from_ftp or do_upload) and not self.connect_ftp():
            return False

        succeeded, failed = [], []

        for idx, filename in enumerate(files, 1):
            stem = os.path.splitext(filename)[0]

            print("\n" + "-" * 70)
            print(f"[{idx}/{len(files)}] 处理 {filename}")
            print("-" * 70)

            # 取源：http 从 ZIP、ftp 下载、或本地直读
            if from_http:
                source_file = os.path.join(local_base, f".temp_{stem}.json")
                is_temp = True
                data = FTPToolkit.read_zip_json(http_zip, filename)
                if data is None:
                    print(f"[错误] ZIP 里找不到 {filename}")
                    failed.append((filename, "ZIP 里缺失"))
                    continue
                try:
                    with open(source_file, "wb") as f:
                        f.write(data)
                    print(f"[接口] 已解压 {filename}")
                except Exception as e:
                    print(f"[错误] 写临时文件失败: {e}")
                    failed.append((filename, "写文件失败"))
                    continue
            elif from_ftp:
                source_file = os.path.join(local_base, f".temp_{stem}.json")
                is_temp = True
                if not self.download_file(f"{upload_base}/{filename}", source_file):
                    failed.append((filename, "下载失败"))
                    continue
            else:
                source_file = os.path.join(local_base, filename)
                is_temp = False
                if not os.path.isfile(source_file):
                    print(f"[错误] 本地文件不存在: {source_file}")
                    failed.append((filename, "本地文件不存在"))
                    continue
                print(f"[本地] 使用 {source_file}")

            try:
                result = self.process_content(source_file, stem)
            except Exception as e:
                print(f"[错误] 分页处理异常: {e}")
                result = None

            # 只清理自己下载的临时文件，绝不动用户的本地源文件
            if is_temp:
                try:
                    os.remove(source_file)
                except:
                    pass

            if not result:
                failed.append((filename, "分页失败"))
                continue

            out_dir, stat_file = result

            if not do_upload:
                print(f"[跳过上传] 产物已生成: {out_dir}")
                succeeded.append(filename)
                continue

            print(f"[上传] 开始上传 {stem} 的分页结果...")
            remote_stat = f"{upload_base}/{stem}_category_statistics.json"
            if not self.upload_file(stat_file, remote_stat):
                failed.append((filename, "统计文件上传失败"))
                continue

            remote_content_dir = f"{upload_base}/{stem}_by_category"
            if not self.upload_tree(out_dir, remote_content_dir):
                failed.append((filename, "分页目录上传失败"))
                continue

            succeeded.append(filename)

        self.close()

        done_word = "同步" if do_upload else "分页"
        print("\n" + "=" * 70)
        if failed:
            print(f"⚠️  {done_word}结束（部分失败）".center(70))
            print("=" * 70)
            print(f"\n成功 {len(succeeded)} 个: {', '.join(succeeded) if succeeded else '无'}")
            print(f"失败 {len(failed)} 个:")
            for name, reason in failed:
                print(f"  ❌ {name} — {reason}")
        else:
            print(f"✅ {done_word}完成！".center(70))
            print("=" * 70)
            print(f"\n共处理 {len(succeeded)} 个文件: {', '.join(succeeded)}")

        if not do_upload and succeeded:
            print(f"\n产物目录: {local_base}")

        # 触发通知（有成功项才通知；只分页没推送到线上，不打扰）
        if self.toolkit and succeeded and do_upload:
            self.toolkit.notify_sync_complete(self.config_name)

        return not failed


if __name__ == "__main__":
    toolkit = FTPToolkit()
    toolkit.run()
