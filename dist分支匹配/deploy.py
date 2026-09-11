# -*- coding: utf-8 -*-
# 一键发布：源码当前分支打包 → 同步到 dist 仓库对应分支 → 推送 gitee
# 用法：npm run deploy
import os
import shutil
import subprocess
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.abspath(os.path.join(SRC_DIR, os.pardir, "agent_vue_dist"))


def run(cmd, cwd):
    """跑命令，失败即停"""
    print("==> " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, shell=True)
    if r.returncode != 0:
        sys.exit("!! 命令失败退出：%s" % " ".join(cmd))


branch = subprocess.run(
    "git rev-parse --abbrev-ref HEAD", cwd=SRC_DIR, shell=True,
    capture_output=True, text=True).stdout.strip()
print("==> 源码分支：" + branch)

if not os.path.isdir(os.path.join(DIST_DIR, ".git")):
    sys.exit("!! 找不到 dist 仓库目录：" + DIST_DIR)

run("npm run build:prod", SRC_DIR)

print("==> 同步产物到 dist 仓库（分支 %s）" % branch)
run("git checkout %s 2>nul || git checkout -b %s" % (branch, branch), DIST_DIR)

# 先清空旧产物再拷入，保证删除的文件不会残留
for name in os.listdir(DIST_DIR):
    if name == ".git":
        continue
    path = os.path.join(DIST_DIR, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)

for name in os.listdir(os.path.join(SRC_DIR, "dist")):
    src_sub = os.path.join(SRC_DIR, "dist", name)
    dst_sub = os.path.join(DIST_DIR, name)
    if os.path.isdir(src_sub):
        shutil.copytree(src_sub, dst_sub)
    else:
        shutil.copy2(src_sub, dst_sub)

run("git add -A", DIST_DIR)
# 没有变更就不提交
status = subprocess.run("git diff --cached --quiet", cwd=DIST_DIR, shell=True)
if status.returncode == 0:
    print("==> 没有变更，无需提交")
else:
    run("git commit -m 打包提交", DIST_DIR)
    run("git push -u origin %s" % branch, DIST_DIR)

print("==> 完成：gitee agent_vue_dist 的 %s 分支已更新" % branch)
