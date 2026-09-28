#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_r21.py - 在 wakeup-noads v6.4.0-r2 基线上构建本地 r2.1

包含三类改动：
  1. 必需：江苏科技大学导入修复（内置正方解析器）+ 对应 JxustFix 钩子；
  2. 可选：导入成功后的顶部提示条 / 「温馨提示」弹窗关闭（保留「设置开学日期」对话框）；
  3. 可选：会员弹窗的「去开通 / 去购买」改为与「取消」等价（精简版会员页在线内容被关闭、
     渲染成空白；改为取消语义后既不跳空白页，也不会启用任何 VIP 功能）；
  4. 必需：AndroidManifest 的 versionName -> 6.4.0-r2.1、versionCode -> 531
     （每处修改要求恰好命中一次，改完再回读校验）。

审核加固（见 buildlib.py）：口令不内置、路径全相对仓库、工作目录默认临时目录、
smali 树带输入指纹、必需锚点缺失即失败、可选锚点缺失记 WARN 并写入构建报告。

用法：
  export WAKEUP_KEYSTORE=keystore/my.jks WAKEUP_KS_ALIAS=myalias WAKEUP_KS_PASS='…'
  python scripts/build_r21.py --base-apk base/wakeup-noads-v6.4.0-r2-original.apk \
      --out dist/wakeup-noads-v6.4.0-r2.1-jxustfix.apk
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import axml_patch  # noqa: E402
import buildlib as bl  # noqa: E402
import wakeup_jxust_fix as wjf  # noqa: E402

PKG_DIR = Path('com/suda/yzune/wakeupschedule')

TARGET_VERSION_NAME = '6.4.0-r2.1'
TARGET_VERSION_CODE = 531
BASE_VERSION_NAME = '6.4.0'

# 「去开通 / 去购买」→ 与「取消」等价（可选增强）
REVERT_TO_CANCEL = [
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule\o0Oo0oo.smali',
     '    iget-object v0, p0, Lcom/suda/yzune/wakeupschedule/schedule/o0Oo0oo;->o00OOO0O:'
     'Lcom/suda/yzune/wakeupschedule/schedule/o0OO00O;\n'
     '    invoke-static {v0, p1}, Lcom/suda/yzune/wakeupschedule/schedule/o0OO00O;->OooOo0O'
     '(Lcom/suda/yzune/wakeupschedule/schedule/o0OO00O;Landroid/view/View;)V\n',
     '夜间模式「去开通」→取消'),
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule\o0O0OO0.smali',
     '    iget-object v0, p0, Lcom/suda/yzune/wakeupschedule/schedule/o0O0OO0;->o00OOO0O:'
     'Lcom/suda/yzune/wakeupschedule/schedule/ScheduleFragment;\n'
     '    invoke-static {v0, p1}, Lcom/suda/yzune/wakeupschedule/schedule/ScheduleFragment;->o0000o'
     '(Lcom/suda/yzune/wakeupschedule/schedule/ScheduleFragment;Landroid/view/View;)V\n',
     '简洁模式「去开通」→取消'),
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule_settings\o000oOoO.smali',
     '    iget-object v0, p0, Lcom/suda/yzune/wakeupschedule/schedule_settings/o000oOoO;->o00OOO0O:'
     'Lcom/suda/yzune/wakeupschedule/schedule_settings/MainStyleFragment;\n'
     '    invoke-static {v0, p1}, Lcom/suda/yzune/wakeupschedule/schedule_settings/MainStyleFragment;'
     '->OoooOO0(Lcom/suda/yzune/wakeupschedule/schedule_settings/MainStyleFragment;Landroid/view/View;)V\n',
     '样式页「去开通」→取消'),
]

# 会员页自己的「去开通 / 去购买」只跳收银台，不涉及功能状态（可选，空操作即可）
VIP_PAGE_NOOP = [
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0O00000.smali'),
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0oOOo.smali'),
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0O000o0.smali'),
]

ONCLICK_RE = r'(?m)^\.method public final onClick\(Landroid/view/View;\)V'


def rewrite_onclick(path: Path, body: str, name: str, rec: bl.PatchRecorder) -> None:
    """把监听器 onClick 的方法体替换为给定指令（可选补丁）。"""
    if not path.exists():
        rec.add(name, required=False, status='warn', detail=f'{path.name} 不存在')
        return
    text = wjf.read(path)
    span = wjf.method_span(text, ONCLICK_RE)
    if not span:
        rec.add(name, required=False, status='fail', detail='未找到 onClick(View) 方法')
        raise bl.PatchError(f'{path.name} 结构异常：没有 onClick(View)')
    if body in text[span[0]:span[1]]:
        rec.add(name, required=False, status='skip', detail='补丁已存在')
        return
    new_method = ('.method public final onClick(Landroid/view/View;)V\n'
                  '    .registers 3\n\n    .line 1\n' + body + '\n    return-void\n')
    wjf.write(path, text[:span[0]] + new_method + text[span[1]:])
    rec.add(name, required=False, status='ok')


def noop_onclick(path: Path, name: str, rec: bl.PatchRecorder) -> None:
    """把监听器 onClick 变成空操作（可选补丁）。"""
    if not path.exists():
        rec.add(name, required=False, status='warn', detail=f'{path.name} 不存在')
        return
    text = wjf.read(path)
    span = wjf.method_span(text, ONCLICK_RE)
    if not span:
        rec.add(name, required=False, status='fail', detail='未找到 onClick(View) 方法')
        raise bl.PatchError(f'{path.name} 结构异常：没有 onClick(View)')
    off = wjf.first_instruction_offset(text, span)
    if off is None:
        rec.add(name, required=False, status='fail', detail='无法定位方法首指令')
        raise bl.PatchError(f'{path.name} 无法定位 onClick 首指令')
    if 'return-void' in text[span[0]:off]:
        rec.add(name, required=False, status='skip', detail='补丁已存在')
        return
    line_end = text.find('\n', off)
    wjf.write(path, text[:off] + '    return-void' + text[line_end:])
    rec.add(name, required=False, status='ok')


def build(args) -> dict:
    rec = bl.PatchRecorder()
    tools = bl.resolve_tools(args.tools_dir)
    signing = bl.resolve_signing(args.keystore, args.ks_alias, args.ks_pass,
                                 args.ks_env_file, interactive=not args.no_interactive)
    base = Path(args.base_apk).resolve()
    if not base.exists():
        raise bl.BuildError(f'输入 APK 不存在: {base}')
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    base_fp = bl.sha256_file(base)
    log = bl.log
    log(f'输入 APK : {base}')
    log(f'  SHA-256: {base_fp}')
    log(f'目标版本 : {TARGET_VERSION_NAME} / versionCode {TARGET_VERSION_CODE}')
    log(f'签名      : {Path(signing.keystore).name} / {signing.alias}（口令来源：{signing.source}）')

    # 基线版本核对：避免把"已经是 r2.1"的包再打一遍
    base_attrs = axml_patch.read_attrs(base, ('versionName', 'versionCode'))
    log(f'基线 manifest: {base_attrs}')
    if base_attrs.get('versionName') != BASE_VERSION_NAME:
        log(f'  [WARN] 基线 versionName={base_attrs.get("versionName")!r}，'
            f'预期 {BASE_VERSION_NAME!r}；请确认这就是目标基线')

    work = bl.prepare_workdir(args.workdir, keep=args.keep_workdir)
    log(f'工作目录  : {work}')
    try:
        dexdir = work / 'dex'
        trees = {}
        for dex in ('classes5.dex', 'classes6.dex'):
            dex_path = bl.extract_dex(base, dex, dexdir)
            trees[dex] = bl.baksmali_dex(args.java, tools['baksmali'], dex_path,
                                         work / dex.replace('.dex', ''), base_fp,
                                         force=args.force_recompile)

        log('== 1. 江苏科技大学导入修复（必需）==')
        tree6 = trees['classes6.dex'].tree
        for dt in trees.values():
            wjf.revert_short_circuits(dt.tree / PKG_DIR / 'aaa' / 'utils' / 'o00O0000.smali', rec)
        wjf.patch_jxust_fix_class(tree6, rec)
        wjf.patch_login_activity(tree6 / PKG_DIR / 'schedule_import' / 'LoginWebActivity.smali', rec)

        log('== 2. 导入后打扰性 UI（可选）==')
        sch = tree6 / PKG_DIR / 'schedule'
        wjf.patch_import_banner(sch / 'SchedulePullDownLayout.smali', rec)
        wjf.patch_import_tip_dialog(sch / 'ScheduleFragment$handleIntent$1.smali', rec)

        log('== 3. 会员弹窗「去开通」改为与取消等价（可选）==')
        by_short = {k.replace('.dex', ''): v.tree for k, v in trees.items()}
        for dex, rel, body, label in REVERT_TO_CANCEL:
            rewrite_onclick(by_short[dex] / rel, body, label, rec)
        for dex, rel in VIP_PAGE_NOOP:
            noop_onclick(by_short[dex] / rel, f'会员页 {Path(rel).name} 保持空操作', rec)

        if rec.failed_required or (args.strict and rec.summary()['warn']):
            raise bl.PatchError('存在未满足的补丁要求，终止产包'
                                f'（failed_required={len(rec.failed_required)}, strict={args.strict}）')

        log('== 4. 回编 + manifest + 重打包 + 签名 ==')
        replacements = {}
        for dex, dt in trees.items():
            out_dex = work / ('patched-' + dex)
            bl.run([args.java, '-Xmx4g', '-jar', tools['smali'], 'a', str(dt.tree), '-o', str(out_dex)])
            if not out_dex.exists() or out_dex.stat().st_size < 1024:
                raise bl.BuildError(f'{dex} 回编产物异常: {out_dex}')
            replacements[dex] = out_dex

        axml_out = work / 'AndroidManifest.xml'
        axml_report = axml_patch.patch_manifest(
            base, axml_out,
            set_string=[(BASE_VERSION_NAME, TARGET_VERSION_NAME)],
            set_int=[('versionCode', str(TARGET_VERSION_CODE))],
            expect_once=True)
        log(f'  manifest 改写: {axml_report}')
        replacements['AndroidManifest.xml'] = axml_out

        unsigned = work / 'wakeup-r21-unsigned.apk'
        bl.rebuild_apk(base, unsigned, replacements)
        bl.sign_apk(args.java, tools['signer'], unsigned, out, signing)

        # 产物自检：版本号、关键 smali 改动是否真的进了产物
        final_attrs = axml_patch.read_attrs(out, ('versionName', 'versionCode'))
        ok_name = final_attrs.get('versionName') == TARGET_VERSION_NAME
        ok_code = final_attrs.get('versionCode') == TARGET_VERSION_CODE
        rec.add('产物 versionName', required=True, status='ok' if ok_name else 'fail',
                detail=str(final_attrs.get('versionName')))
        rec.add('产物 versionCode', required=True, status='ok' if ok_code else 'fail',
                detail=str(final_attrs.get('versionCode')))
        if not (ok_name and ok_code):
            raise bl.BuildError(f'产物 manifest 校验失败: {final_attrs}')
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            for dex in ('classes5.dex', 'classes6.dex'):
                rec.add(f'产物包含 {dex}', required=True,
                        status='ok' if dex in names else 'fail')
                if dex not in names:
                    raise bl.BuildError(f'产物缺少 {dex}')

        report = {
            'task': 'build_r21',
            'base_apk': str(base),
            'base_apk_sha256': base_fp,
            'base_manifest': base_attrs,
            'out_apk': str(out),
            'out_apk_sha256': bl.sha256_file(out),
            'out_manifest': final_attrs,
            'signing': {'keystore': Path(signing.keystore).name, 'alias': signing.alias,
                        'password_source': signing.source},
            'tools': {k: {'name': Path(v).name, 'sha256': bl.sha256_file(v)}
                      for k, v in tools.items()},
            'dex_trees': {d: {'reused': dt.reused, 'fingerprint': dt.fingerprint}
                          for d, dt in trees.items()},
            'axml': axml_report,
            'patches': rec.summary(),
            'strict': bool(args.strict),
        }
        bl.write_report(out.with_suffix(out.suffix + '.build-report.json'), report)
        bl.log(f'产物: {out}')
        bl.log(f'  SHA-256: {report["out_apk_sha256"]}')
        return report
    finally:
        bl.clean_workdir(work, keep=args.keep_workdir)


def main() -> int:
    ap = argparse.ArgumentParser(description='构建 wakeup-noads v6.4.0-r2.1（科大一键导入修复）')
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--tools-dir', help='baksmali/smali/uber-apk-signer 所在目录（默认仓库 tools/）')
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
    args = ap.parse_args()
    try:
        build(args)
        return 0
    except (bl.BuildError, axml_patch.AxmlPatchError) as e:
        print(f'\n构建失败: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
