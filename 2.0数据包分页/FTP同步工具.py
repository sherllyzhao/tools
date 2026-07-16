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
from datetime import datetime
from ftplib import FTP

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
        print("  1. 执行 FTP 同步 (下载→分页→上传)")
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
                return json.load(f)
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
            "ftp_source_path": "/jsonDatas/content.json",
            "ftp_upload_path": "/jsonDatas",
        }

        print("\n解析结果：")
        print(f"  FTP 地址: {config['ftp_host']}")
        print(f"  FTP 账户: {config['ftp_user']}")
        print(f"  FTP 密码: {config['ftp_pass']}")
        print(f"  源文件  : {config['ftp_source_path']} (固定)")
        print(f"  上传目录: {config['ftp_upload_path']} (固定)")

        # 本地目录因项目而异，仍需询问
        config["local_base_dir"] = input("\n本地基础目录 (分页文件存这里): ").strip()
        page_size_str = input("每页条数 (默认 20): ").strip()
        config["page_size"] = int(page_size_str) if page_size_str.isdigit() else 20

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
        print(f"[5/5] 检查源文件 ({config['ftp_source_path']})...")
        try:
            size = ftp.size(config["ftp_source_path"])
            print(f"✅ 文件存在，大小: {size} bytes")
        except Exception as e:
            print(f"⚠️  文件检查失败: {e}")

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

    def view_config(self, config_name):
        """查看配置详情"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print(f"\n配置: {config_name}")
        print("-" * 70)
        for key, value in config.items():
            if key == "ftp_pass":
                print(f"  {key}: {value[:3]}{'*' * (len(value) - 3)}")
            else:
                print(f"  {key}: {value}")
        print("-" * 70)

    def sync_ftp(self, config_name):
        """执行 FTP 同步"""
        config = self.load_config(config_name)
        if not config:
            print("❌ 配置不存在")
            return

        print("\n" + "=" * 70)
        print(f"FTP 同步 - {config_name}".center(70))
        print("=" * 70)

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

    def config_menu(self, config_name):
        """单个配置的菜单"""
        self.clear_screen()
        print(f"\n配置: {config_name}\n")
        print("  1. 查看详情")
        print("  2. 更新密码")
        print("  3. 删除配置")
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
                    input("\n按回车开始同步...")
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

    def process_content(self, source_file):
        """处理内容：分页、删除 details 字段"""
        print(f"\n[处理] 读取 {source_file}...")
        with open(source_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("[错误] 顶层不是数组")
            return False

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
        out_dir = os.path.join(local_base, "content_by_category")
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

                fn = os.path.join(cat_dir, f"content_{cid}_{i + 1}.json")
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
        stat_file = os.path.join(local_base, "content_category_statistics.json")
        with open(stat_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n[完成] {total_files} 个文件生成完毕")
        return True

    def close(self):
        """关闭 FTP 连接"""
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                self.ftp.close()

    def run(self):
        """主工作流"""
        print("\n" + "=" * 70)
        print("开始同步".center(70))
        print("=" * 70)

        if not self.connect_ftp():
            return False

        temp_file = os.path.join(self.config["local_base_dir"], ".temp_content.json")
        if not self.download_file(self.config["ftp_source_path"], temp_file):
            self.close()
            return False

        if not self.process_content(temp_file):
            self.close()
            return False

        try:
            os.remove(temp_file)
        except:
            pass

        print("\n" + "-" * 70)
        print("[上传] 开始上传分页结果...")

        stat_file = os.path.join(self.config["local_base_dir"], "content_category_statistics.json")
        remote_stat = self.config["ftp_upload_path"] + "/content_category_statistics.json"
        if not self.upload_file(stat_file, remote_stat):
            self.close()
            return False

        content_dir = os.path.join(self.config["local_base_dir"], "content_by_category")
        remote_content_dir = self.config["ftp_upload_path"] + "/content_by_category"
        if not self.upload_tree(content_dir, remote_content_dir):
            self.close()
            return False

        print("\n" + "=" * 70)
        print("✅ 同步完成！".center(70))
        print("=" * 70)
        self.close()

        # 触发通知
        if self.toolkit:
            self.toolkit.notify_sync_complete(self.config_name)

        return True


if __name__ == "__main__":
    toolkit = FTPToolkit()
    toolkit.run()
