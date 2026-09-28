#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wakeup_jxust_fix.py - 修复「江苏科技大学（正方教务）」课表导入失败（可复现构建）

背景
----
WakeUp 课程表把江苏科技大学的导入方式登记为 importType="ziyan"，即导入时先向
WakeUp 服务端请求一份动态解析脚本（/wakeup/script/enplugin）。在部分环境下这条
加密请求链会失败（例如 x86 模拟器上 libbaseutil.so 的 Antispam 初始化不成功，
RC4 密钥为空 -> EncryptNet 抛 ArrayIndexOutOfBoundsException），用户看到的是：

    导入失败>_<请认真看一下提示。此页面似乎没有课程信息。
    详细的错误信息如下：
    com.android.volley.ResponseContentError

而实际上教务页面已经登录、个人课表也已经显示出来。

修复（全部为 smali 层补丁，不触碰解析实现）
----
1) 必需：让江苏科技大学改走 App 自带的正方（zf）解析器 —— 新增 JxustFix.apply()，
   在 LoginWebActivity.onCreate() 读完 intent 之后钩一次；命中学校名时把 ViewModel
   的导入类型字段改为 zf / wakeup。
2) 可选：关闭导入成功后不必要的打扰性 UI（顶部「导课成功」提示条、导入后「温馨提示」
   弹窗），保留含「设置开学日期」按钮的对话框。
3) 可选：若目标版本仍带有 wakeup-noads 精简补丁注入的「账号/会话只读方法提前返回」，
   一并撤销（与上游 6.4.0-r1-issue3 的修复一致）。

用法（默认工具路径取仓库内 tools/，无需本机绝对路径）
----
  export WAKEUP_KEYSTORE=my-release.jks      # 或 --keystore
  export WAKEUP_KS_ALIAS=myalias
  export WAKEUP_KS_PASS='…'                  # 或写进仓库根 .signing.env（勿入库）
  python scripts/wakeup_jxust_fix.py --base-apk wakeup-noads.apk --out out.apk

审核加固说明见 buildlib.py 顶部注释：必需锚点缺失即失败退出；每个替换要求恰好命中
一次；补丁后回读校验；反编译树带输入指纹；工作目录默认临时目录。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import buildlib as bl  # noqa: E402

JXUST = '\u6c5f\u82cf\u79d1\u6280\u5927\u5b66'          # 江苏科技大学
DIALOG_CLASS = 'Lo00oOOO0/Oooo000;'                     # AlertDialog builder used by the tip
IMPORT_VM = 'Lcom/suda/yzune/wakeupschedule/schedule_import/ImportViewModel;'
LOGIN_ACT = 'Lcom/suda/yzune/wakeupschedule/schedule_import/LoginWebActivity;'
PKG_DIR = os.path.join('com', 'suda', 'yzune', 'wakeupschedule')

JXUST_FIX_SMALI = '''.class public final Lcom/suda/yzune/wakeupschedule/schedule_import/JxustFix;
.super Ljava/lang/Object;
.source "JxustFix.java"


# direct methods
.method public constructor <init>()V
    .registers 1

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

# 把「江苏科技大学」切到内置正方解析器（importType=zf, realImportType=wakeup）。
# 直接写 ViewModel 的字段，字段名在各版本间稳定，避免依赖混淆后的 setter 名。
.method public static apply(%(login_act)s)V
    .registers 5

    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
    move-result-object v0

    const-string v1, "school_name"

    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0

    const-string v1, "%(school)s"

    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0

    if-eqz v0, :cond_end

    invoke-virtual {p0}, %(login_act)s->OoooooO()%(vm)s
    move-result-object v0

    const-string v1, "zf"

    iput-object v1, v0, %(vm)s->%(import_field)s:Ljava/lang/String;

    const-string v1, "wakeup"

    iput-object v1, v0, %(vm)s->%(real_field)s:Ljava/lang/String;

    :cond_end
    return-void
.end method
'''

# ImportViewModel 的两个字段：importType / realImportType（6.3.0 与 6.4.0 系列一致）。
# 运行期会先在反编译产物里确认这两个字段存在，不存在就让构建失败，不写死假设。
IMPORT_TYPE_FIELD = 'OooO0o0'
REAL_IMPORT_TYPE_FIELD = 'OooO0Oo'

HOOK_CALL = ('    invoke-static {p0}, Lcom/suda/yzune/wakeupschedule/schedule_import/'
             'JxustFix;->apply(Lcom/suda/yzune/wakeupschedule/schedule_import/'
             'LoginWebActivity;)V')


def read(p) -> str:
    return Path(p).read_text(encoding='utf-8')


def write(p, s: str) -> None:
    Path(p).write_text(s, encoding='utf-8')


def method_span(text, header_regex):
    """返回匹配方法的 (start, end) 字符偏移。"""
    m = re.search(header_regex, text)
    if not m:
        return None
    end = text.find('\n.end method', m.start())
    return (m.start(), end if end != -1 else len(text))


def first_instruction_offset(text, span):
    """方法体内第一条指令行的偏移（跳过指令块、注解块、空行）。"""
    pos = text.find('\n', span[0]) + 1
    in_annotation = 0
    while True:
        line_end = text.find('\n', pos)
        if line_end == -1:
            return None
        line = text[pos:line_end].strip()
        if line.startswith('.annotation'):
            in_annotation += 1
        elif line.startswith('.end annotation'):
            in_annotation = max(0, in_annotation - 1)
        elif not in_annotation and line and not line.startswith('.') and not line.startswith('#'):
            return pos
        pos = line_end + 1


# --------------------------------------------------------------------------- #
# 补丁实现
# --------------------------------------------------------------------------- #
def render_jxust_template(tree6: Path, rec: bl.PatchRecorder) -> str:
    """按目标版本确认 ImportViewModel 字段后渲染 JxustFix.smali 模板。

    必需字段：导入类型（importType）与 realImportType。两者在 6.3.0/6.4.0 系列里分别是
    OooO0o0 / OooO0Oo，但这里先在反编译产物里确认存在，缺失即失败，不写死假设。
    """
    vm_path = tree6 / PKG_DIR / 'schedule_import' / 'ImportViewModel.smali'
    if not vm_path.exists():
        rec.add('ImportViewModel 存在', required=True, status='fail',
                detail=str(vm_path))
        raise bl.PatchError(f'缺少 {vm_path}')
    text = read(vm_path)
    fields = set(re.findall(r'\.field public (\w+):Ljava/lang/String;', text))
    for name in (IMPORT_TYPE_FIELD, REAL_IMPORT_TYPE_FIELD):
        if name not in fields:
            rec.add(f'ImportViewModel 字段 {name}', required=True, status='fail',
                    detail='字段名与预期不符，需人工确认新版本字段')
            raise bl.PatchError(f'ImportViewModel 里没有字段 {name}')
    rec.add(f'ImportViewModel 字段 {IMPORT_TYPE_FIELD}/{REAL_IMPORT_TYPE_FIELD}',
            required=True, status='ok')
    return JXUST_FIX_SMALI % {
        'login_act': LOGIN_ACT,
        'vm': IMPORT_VM,
        'school': ''.join('\\u%04x' % ord(c) for c in JXUST),
        'import_field': IMPORT_TYPE_FIELD,
        'real_field': REAL_IMPORT_TYPE_FIELD,
    }


def patch_jxust_fix_class(tree6: Path, rec: bl.PatchRecorder) -> None:
    """新增 JxustFix.smali（必需）。"""
    imp = tree6 / PKG_DIR / 'schedule_import'
    bl.require(imp.is_dir(), f'schedule_import 目录不存在: {imp}')
    template = render_jxust_template(tree6, rec)
    write(imp / 'JxustFix.smali', template)
    rec.add('新增 schedule_import/JxustFix.smali', required=True, status='ok')


def patch_login_activity(path: Path, rec: bl.PatchRecorder) -> None:
    """在 LoginWebActivity.onCreate() 里钩一次 JxustFix.apply（必需）。"""
    text = read(path)
    if HOOK_CALL in text:
        n = text.count(HOOK_CALL)
        if n != 1:
            rec.add('LoginWebActivity 注入 JxustFix 钩子', required=True, status='fail',
                    detail=f'已存在 {n} 处（应为 1）')
            raise bl.PatchError('LoginWebActivity 里 JxustFix 钩子数量异常')
        rec.add('LoginWebActivity 注入 JxustFix 钩子', required=True, status='skip',
                detail='补丁已存在')
        return
    anchor = 'invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;'
    gen = 'getExtras()Landroid/os/Bundle;'
    school = text.find('const-string v2, "school_name"')
    if school == -1:
        school = text.find('"school_name"')
    pos = text.find(anchor, school if school != -1 else 0)
    while pos != -1 and gen not in text[pos:pos + 400]:
        pos = text.find(anchor, pos + 1)
    if pos == -1:
        rec.add('LoginWebActivity 注入 JxustFix 钩子', required=True, status='fail',
                detail='未找到 onCreate 中读完 school_name 后的 getIntent 锚点')
        raise bl.PatchError('LoginWebActivity 锚点未找到（新版本可能改了 onCreate 结构）')
    write(path, text[:pos] + HOOK_CALL + '\n\n' + text[pos:])
    bl.assert_patched(path, [(re.escape(HOOK_CALL), True)], rec=rec)


def revert_short_circuits(path: Path, rec: bl.PatchRecorder) -> int:
    """撤销精简补丁注入的「常量 + 提前 return」（可选：老版本才有）。"""
    if not path.exists():
        rec.add('恢复账号/会话只读方法（o00O0000）', required=False, status='warn',
                detail=f'{path.name} 不存在')
        return 0
    text = read(path)
    result, reverted = text, 0
    for m in list(re.finditer(r'(?m)^\.method\b[^\n]*\n', text))[::-1]:
        start = m.start()
        end = text.find('\n.end method', start)
        lines = text[start:end].split('\n')
        idx = next((i for i, l in enumerate(lines)
                    if l.strip() and not l.strip().startswith(('.', '#'))), None)
        if idx is None or idx + 1 >= len(lines):
            continue
        const, ret = lines[idx].strip(), lines[idx + 1].strip()
        if re.match(r'^const(-string|/4|/16)?\s', const) and \
                re.match(r'^return(-object|-void|-wide)?\b', ret):
            rest = [l for l in lines[idx + 2:] if l.strip() and not l.strip().startswith('.')]
            if not rest:
                continue
            del lines[idx:idx + 2]
            while idx < len(lines) and not lines[idx].strip():
                del lines[idx]
            result = result[:start] + '\n'.join(lines) + result[end:]
            reverted += 1
    if reverted:
        write(path, result)
        bl.assert_patched(path, [(r'(?m)^\.method', True)], rec=rec)
    rec.add('恢复账号/会话只读方法（o00O0000）', required=False,
            status='ok' if reverted else 'skip',
            detail=f'撤销 {reverted} 处短路' if reverted else '目标版本没有该短路')
    return reverted


def patch_import_banner(path: Path, rec: bl.PatchRecorder) -> None:
    """SchedulePullDownLayout.showImportFeedback(...) -> no-op（可选）。"""
    name = '关闭导入成功顶部提示条（showImportFeedback）'
    if not path.exists():
        rec.add(name, required=False, status='warn', detail=f'{path.name} 不存在')
        return
    text = read(path)
    span = method_span(text, r'(?m)^\.method public final showImportFeedback\(')
    if not span:
        rec.add(name, required=False, status='warn', detail='未找到 showImportFeedback 方法')
        return
    off = first_instruction_offset(text, span)
    if off is None:
        # 方法存在但定位不到首指令：不允许静默跳过
        rec.add(name, required=False, status='fail', detail='无法定位方法首指令')
        raise bl.PatchError('showImportFeedback 方法结构异常，无法定位首指令')
    if 'return-void' in text[span[0]:off]:
        rec.add(name, required=False, status='skip', detail='补丁已存在')
        return
    line_end = text.find('\n', off)
    write(path, text[:off] + '    return-void' + text[line_end:])
    rec.add(name, required=False, status='ok')


def patch_import_tip_dialog(path: Path, rec: bl.PatchRecorder) -> None:
    """ScheduleFragment$handleIntent$1 -> 跳过「温馨提示」弹窗（可选）。"""
    name = '关闭导入后「温馨提示」弹窗'
    if not path.exists():
        rec.add(name, required=False, status='warn', detail=f'{path.name} 不存在')
        return
    text = read(path)
    if '\\u6e29\\u99a8\\u63d0\\u793a' not in text:
        rec.add(name, required=False, status='warn', detail='未找到该弹窗调用')
        return
    rx = re.compile(
        r'(?m)^([ \t]*)if-eqz ([pv]\d+), (:\w+)((?:[ \t]*\n(?:[ \t]*\.line \d+)?)*)\n'
        r'[ \t]*new-instance \w+, ' + re.escape(DIALOG_CLASS))
    m = rx.search(text)
    if not m:
        if re.search(r'(?m)^[ \t]*goto :\w+\s*$', text):
            rec.add(name, required=False, status='skip', detail='补丁可能已存在')
            return
        rec.add(name, required=False, status='warn', detail='未匹配到弹窗守卫模式')
        return
    write(path, text[:m.start()] + m.group(1) + 'goto ' + m.group(3) + m.group(4)
          + text[m.end():])
    rec.add(name, required=False, status='ok')


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build(args) -> dict:
    rec = bl.PatchRecorder()
    tools = bl.resolve_tools(args.tools_dir)
    signing = bl.resolve_signing(args.keystore, args.ks_alias, args.ks_pass,
                                 args.ks_env_file, interactive=not args.no_interactive)
    base = Path(args.base_apk).resolve()
    bl.require(base.exists(), f'输入 APK 不存在: {base}')
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    base_fp = bl.sha256_file(base)
    log = bl.log
    log(f'输入 APK : {base}')
    log(f'  SHA-256: {base_fp}')
    log(f'工具      : { {k: Path(v).name for k, v in tools.items()} }')
    log(f'签名      : {Path(signing.keystore).name} / {signing.alias}（口令来源：{signing.source}）')

    work = bl.prepare_workdir(args.workdir, keep=args.keep_workdir)
    log(f'工作目录  : {work}')
    try:
        dexdir = work / 'dex'
        trees = {}
        for dex in args.dexes:
            dex_path = bl.extract_dex(base, dex, dexdir)
            trees[dex] = bl.baksmali_dex(args.java, tools['baksmali'], dex_path,
                                         work / dex.replace('.dex', ''), base_fp,
                                         force=args.force_recompile)

        log('== 应用补丁 ==')
        if 'classes6.dex' not in trees:
            raise bl.BuildError('本次构建需要 classes6.dex')
        tree6 = trees['classes6.dex'].tree

        for dex, dt in trees.items():
            revert_short_circuits(dt.tree / PKG_DIR / 'aaa' / 'utils' / 'o00O0000.smali', rec)

        patch_jxust_fix_class(tree6, rec)
        patch_login_activity(tree6 / PKG_DIR / 'schedule_import' / 'LoginWebActivity.smali', rec)

        sch = tree6 / PKG_DIR / 'schedule'
        patch_import_banner(sch / 'SchedulePullDownLayout.smali', rec)
        patch_import_tip_dialog(sch / 'ScheduleFragment$handleIntent$1.smali', rec)

        if rec.failed_required or (args.strict and rec.summary()['warn']):
            raise bl.PatchError('存在未满足的补丁要求，终止产包'
                                f'（failed_required={len(rec.failed_required)}, strict={args.strict}）')

        log('== 回编 ==')
        replacements = {}
        for dex, dt in trees.items():
            out_dex = work / ('patched-' + dex)
            bl.run([args.java, '-Xmx4g', '-jar', tools['smali'], 'a', str(dt.tree),
                    '-o', str(out_dex)])
            if not out_dex.exists() or out_dex.stat().st_size < 1024:
                raise bl.BuildError(f'{dex} 回编产物异常: {out_dex}')
            replacements[dex] = out_dex

        log('== 重打包 + 签名 ==')
        unsigned = work / 'wakeup-jxust-unsigned.apk'
        bl.rebuild_apk(base, unsigned, replacements)
        bl.sign_apk(args.java, tools['signer'], unsigned, out, signing)

        report = {
            'task': 'wakeup_jxust_fix',
            'base_apk': str(base),
            'base_apk_sha256': base_fp,
            'out_apk': str(out),
            'out_apk_sha256': bl.sha256_file(out),
            'signing': {'keystore': Path(signing.keystore).name, 'alias': signing.alias,
                        'password_source': signing.source},
            'tools': {k: {'name': Path(v).name, 'sha256': bl.sha256_file(v)}
                      for k, v in tools.items()},
            'dex_trees': {d: {'reused': dt.reused, 'fingerprint': dt.fingerprint}
                          for d, dt in trees.items()},
            'patches': rec.summary(),
            'strict': bool(args.strict),
        }
        bl.write_report(out.with_suffix(out.suffix + '.build-report.json'), report)
        bl.log(f'产物: {out}  SHA-256={report["out_apk_sha256"]}')
        return report
    finally:
        bl.clean_workdir(work, keep=args.keep_workdir)


def main() -> int:
    ap = argparse.ArgumentParser(description='江苏科技大学导入修复（通用 smali 补丁构建）')
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--tools-dir', help='baksmali/smali/uber-apk-signer 所在目录（默认仓库 tools/）')
    ap.add_argument('--baksmali')
    ap.add_argument('--smali')
    ap.add_argument('--signer')
    ap.add_argument('--keystore', help='不设默认值；也可用 WAKEUP_KEYSTORE')
    ap.add_argument('--ks-alias', help='不设默认值；也可用 WAKEUP_KS_ALIAS')
    ap.add_argument('--ks-pass', help='不设默认值；也可用 WAKEUP_KS_PASS 或 .signing.env')
    ap.add_argument('--ks-env-file', help='口令文件（默认仓库根 .signing.env，勿入库）')
    ap.add_argument('--workdir', help='自定义工作目录（默认系统临时目录；非本工具创建的目录不会被清理）')
    ap.add_argument('--keep-workdir', action='store_true')
    ap.add_argument('--force-recompile', action='store_true', help='忽略 smali 树缓存')
    ap.add_argument('--strict', action='store_true', help='可选补丁未命中时也失败')
    ap.add_argument('--no-interactive', action='store_true', help='禁止交互式输入口令')
    ap.add_argument('--java', default='java')
    ap.add_argument('--dexes', nargs='*', default=['classes5.dex', 'classes6.dex'])
    args = ap.parse_args()

    # 允许用显式 jar 覆盖仓库内工具
    if args.baksmali or args.smali or args.signer:
        t = bl.resolve_tools(args.tools_dir)
        for key, val in (('baksmali', args.baksmali), ('smali', args.smali),
                         ('signer', args.signer)):
            if val:
                p = Path(val)
                if not p.exists():
                    print(f'错误: 指定的 {key} 不存在: {p}', file=sys.stderr)
                    return 2
                t[key] = str(p)
        bl.resolve_tools = lambda tools_dir=None, _t=t: _t  # type: ignore

    try:
        build(args)
        return 0
    except bl.BuildError as e:
        print(f'\n构建失败: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
