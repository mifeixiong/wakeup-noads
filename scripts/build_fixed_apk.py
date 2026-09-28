#!/usr/bin/env python3
"""Rebuild a patched WakeUp (wakeup-noads) APK that makes the 江苏科技大学
(Jiangsu University of Science and Technology) timetable import work.

The script expects a *baksmali* tree of the source APK's dex files:

    java -jar baksmali.jar d classes5.dex -o smali5
    java -jar baksmali.jar d classes6.dex -o smali6

It then applies the two smali patches, reassembles the dex files,
rebuilds the APK (preserving zip layout and the required resources.arsc
alignment), and signs it.

usage:
  python build_fixed_apk.py --base-apk <src.apk> --baksmali <baksmali.jar>
                            --smali <smali.jar> --signer <uber-apk-signer.jar>
                            --keystore <ks.jks> --out <out.apk>
                            [--workdir <dir>]
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildlib  # noqa: E402  审核加固：口令外部化 / 工作目录安全 / 缓存指纹

PATCHDIR = os.path.join(HERE, '..', 'patch')

# ---------------------------------------------------------------- patch data
# classes5: remove the three injected early returns (aaa/utils/o00O0000)
SHORTCIRCUIT_PATCHES = [
    (
        'o00O0000.smali',
        '''.method public static OooO0OO()Ljava/lang/String;
    .registers 1

    const-string v0, ""

    return-object v0

    .line 1
    sget-object v0, Lcom/suda/yzune/wakeupschedule/aaa/preference/CommonPreference;->ACCOUNT_DXUSS:Lcom/suda/yzune/wakeupschedule/aaa/preference/CommonPreference;''',
        '''.method public static OooO0OO()Ljava/lang/String;
    .registers 1

    .line 1
    sget-object v0, Lcom/suda/yzune/wakeupschedule/aaa/preference/CommonPreference;->ACCOUNT_DXUSS:Lcom/suda/yzune/wakeupschedule/aaa/preference/CommonPreference;''',
    ),
    (
        'o00O0000.smali',
        '''.method public static OooO0oO()Lcom/suda/yzune/wakeupschedule/aaa/v1/UserInfo;
    .registers 2

    const/4 v0, 0x0

    return-object v0

    .line 1
    :try_start_2''',
        '''.method public static OooO0oO()Lcom/suda/yzune/wakeupschedule/aaa/v1/UserInfo;
    .registers 2

    .line 1
    :try_start_2''',
    ),
    (
        'o00O0000.smali',
        '''.method public static OooOO0()Z
    .registers 1

    const/4 v0, 0x0

    return v0

    .line 1
    invoke-static {}, Lcom/suda/yzune/wakeupschedule/aaa/utils/o00O0000;->OooO0OO()Ljava/lang/String;''',
        '''.method public static OooOO0()Z
    .registers 1

    .line 1
    invoke-static {}, Lcom/suda/yzune/wakeupschedule/aaa/utils/o00O0000;->OooO0OO()Ljava/lang/String;''',
    ),
]

# classes6: route 江苏科技大学 to the native ZF (正方) parser flow
LOGINWEB_INJECT_ANCHOR = '''    :cond_9e
    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
'''
LOGINWEB_INJECT_REPLACEMENT = '''    :cond_9e
    invoke-static {p0}, Lcom/suda/yzune/wakeupschedule/schedule_import/JxustFix;->apply(Lcom/suda/yzune/wakeupschedule/schedule_import/LoginWebActivity;)V

    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
'''

# classes6: drop the three "导课成功" prompts shown after an import
POPUP_PATCHES = [
    # 1. 温馨提示对话框（“记得仔细检查有没有少课…”）: 直接跳到原 else 分支
    (
        'schedule/ScheduleFragment$handleIntent$1.smali',
        '''    .line 148
    if-eqz p1, :cond_116
''',
        '''    .line 148
    goto :cond_116
''',
        'handleIntent: skip 温馨提示 dialog',
    ),
    # 2. “导课成功 / 当前默认开学第一周第一天为…” 对话框：**保留**
    #    （其中的「设置开学日期」按钮是必需功能，故不在此处短路）
    # 3. 课表页顶部“导课成功 / 已导入 N 门课程…（课表正确 / 课表有误）”提示条
    (
        'schedule/SchedulePullDownLayout.smali',
        '''    .end annotation

    .line 1
    const-string v0, "onCorrect"

    .line 2
    .line 3
    invoke-static {p2, v0}, Lkotlin/jvm/internal/o00oO0o;->OooO0oO(Ljava/lang/Object;Ljava/lang/String;)V
''',
        '''    .end annotation

    return-void

    .line 1
    const-string v0, "onCorrect"

    .line 2
    .line 3
    invoke-static {p2, v0}, Lkotlin/jvm/internal/o00oO0o;->OooO0oO(Ljava/lang/Object;Ljava/lang/String;)V
''',
        'showImportFeedback: skip import banner',
    ),
]

ALIGN_ENTRY = 'resources.arsc'
SIG_SUFFIX = ('.SF', '.RSA', '.DSA', '.EC')


def run(cmd, **kw):
    # 审核 P1-1：命令回显统一走 buildlib.run（对口令类参数打码、输出不截断、非 0 即失败）
    buildlib.run(cmd)


def patch_text(path, old, new, label):
    """锚点必须恰好命中一次；命中 0 次或多次都失败退出（审核 P2-5）。"""
    with open(path, encoding='utf-8') as f:
        data = f.read()
    n = data.count(old)
    if n == 1:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(data.replace(old, new, 1))
        print(f'  [ok]   {label}')
        return
    if n == 0 and new in data:
        print(f'  [skip] {label}: already patched')
        return
    if n == 0:
        sys.exit(f'ERROR: anchor not found for {label} in {path}')
    sys.exit(f'ERROR: anchor matched {n} times for {label} in {path} (expected exactly 1)')


def rebuild_apk(src_apk, dst_apk, dex_map):
    """Rewrite the APK with the patched dex files, keeping the zip layout,
    the compression method of every entry and the 4-byte alignment of
    resources.arsc (required by Android 11+)."""
    src = zipfile.ZipFile(src_apk)
    if os.path.exists(dst_apk):
        os.remove(dst_apk)
    dst = zipfile.ZipFile(dst_apk, 'w', zipfile.ZIP_DEFLATED)
    replaced = dropped = 0
    for info in src.infolist():
        name = info.filename
        if name.startswith('META-INF/') and (name.upper().endswith(SIG_SUFFIX) or name == 'META-INF/MANIFEST.MF'):
            dropped += 1
            continue
        if name in dex_map:
            data = open(dex_map[name], 'rb').read()
            replaced += 1
        else:
            data = src.read(name)
        zi = zipfile.ZipInfo(name, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zi.internal_attr = info.internal_attr
        zi.create_system = info.create_system
        extra = b''
        if info.compress_type == zipfile.ZIP_STORED:
            offset = dst.fp.tell()
            misalign = (offset + 30 + len(name.encode('utf-8'))) % 4
            if misalign:
                need = (4 - misalign) % 4
                length = 4 + need
                extra = (0xD935).to_bytes(2, 'little') + (length - 4).to_bytes(2, 'little') + b'\x00' * (length - 4)
        zi.extra = extra
        dst.writestr(zi, data)
    dst.close()
    src.close()
    print(f'  replaced dex: {replaced}, dropped signature entries: {dropped}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--baksmali', required=True)
    ap.add_argument('--smali', required=True)
    ap.add_argument('--signer', required=True)
    ap.add_argument('--keystore', required=True)
    # 审核 P1-1：不内置默认口令/别名；口令按 CLI → 环境变量 → .signing.env → 交互输入解析
    ap.add_argument('--ks-alias', help='不设默认值；也可用 WAKEUP_KS_ALIAS')
    ap.add_argument('--ks-pass', help='不设默认值；也可用 WAKEUP_KS_PASS 或 .signing.env')
    ap.add_argument('--ks-env-file', help='口令文件（默认仓库根 .signing.env，勿入库）')
    ap.add_argument('--out', required=True)
    # 审核 P1-3：默认使用系统临时目录，且不再无条件 rmtree 用户传入的目录
    ap.add_argument('--workdir', help='自定义工作目录（默认系统临时目录；非本工具创建的目录不会被清理）')
    ap.add_argument('--keep-workdir', action='store_true')
    ap.add_argument('--force-recompile', action='store_true', help='忽略 smali 树缓存')
    ap.add_argument('--java', default='java')
    args = ap.parse_args()

    signing = buildlib.resolve_signing(args.keystore, args.ks_alias, args.ks_pass,
                                       getattr(args, 'ks_env_file', None),
                                       interactive=False)
    work = buildlib.prepare_workdir(args.workdir, keep=args.keep_workdir)
    work = str(work)
    print(f'工作目录: {work}')
    print(f'签名: {os.path.basename(signing.keystore)} / {signing.alias}（口令来源：{signing.source}）')

    # 1. extract dex files -------------------------------------------------
    smali5 = os.path.join(work, 'smali5')
    smali6 = os.path.join(work, 'smali6')
    dexdir = os.path.join(work, 'dex')
    os.makedirs(dexdir, exist_ok=True)
    with zipfile.ZipFile(args.base_apk) as z:
        for name in ('classes5.dex', 'classes6.dex'):
            with open(os.path.join(dexdir, name), 'wb') as f:
                f.write(z.read(name))

    # 2. disassemble -------------------------------------------------------
    # 审核 P1-4：smali 树带输入指纹，指纹不符或要求重编译时删掉旧树，避免旧代码混入新产物
    base_fp = buildlib.sha256_file(args.base_apk)
    for dex, out in (('classes5.dex', smali5), ('classes6.dex', smali6)):
        buildlib.baksmali_dex(args.java, args.baksmali, os.path.join(dexdir, dex),
                              __import__('pathlib').Path(out), base_fp,
                              force=args.force_recompile)

    # 3. apply patches -----------------------------------------------------
    print('applying smali patches')
    base5 = os.path.join(smali5, 'com', 'suda', 'yzune', 'wakeupschedule', 'aaa', 'utils')
    for fname, old, new in SHORTCIRCUIT_PATCHES:
        patch_text(os.path.join(base5, fname), old, new, f'classes5 {fname}')

    base6 = os.path.join(smali6, 'com', 'suda', 'yzune', 'wakeupschedule', 'schedule_import')
    shutil.copyfile(os.path.join(PATCHDIR, 'classes6__JxustFix.smali'), os.path.join(base6, 'JxustFix.smali'))
    print('  [ok]   classes6 JxustFix.smali added')
    patch_text(os.path.join(base6, 'LoginWebActivity.smali'),
               LOGINWEB_INJECT_ANCHOR, LOGINWEB_INJECT_REPLACEMENT,
               'classes6 LoginWebActivity.smali hook')

    sched6 = os.path.join(smali6, 'com', 'suda', 'yzune', 'wakeupschedule', 'schedule')
    for rel, old, new, label in POPUP_PATCHES:
        patch_text(os.path.join(sched6, os.path.basename(rel)), old, new, 'classes6 ' + label)

    # 4. reassemble --------------------------------------------------------
    dex_map = {}
    for dex, tree in (('classes5.dex', smali5), ('classes6.dex', smali6)):
        out_dex = os.path.join(work, 'patched-' + dex)
        run([args.java, '-Xmx4g', '-jar', args.smali, 'a', tree, '-o', out_dex])
        dex_map[dex] = out_dex

    # 5. rebuild + sign ----------------------------------------------------
    unsigned = os.path.join(work, 'wakeup-jxust-unsigned.apk')
    rebuild_apk(args.base_apk, unsigned, dex_map)

    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    # 审核 P1-1：口令只从 signing 解析结果取，回显由 buildlib 打码
    buildlib.sign_apk(args.java, args.signer,
                      __import__('pathlib').Path(unsigned),
                      __import__('pathlib').Path(args.out), signing)
    print('signed apk:', args.out)


if __name__ == '__main__':
    main()
