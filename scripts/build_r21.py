"""Build wakeup-noads v6.4.0-r2.1:
   - 江苏科技大学 import fix (native ZF parser routing)
   - import banner / tip dialog removed ("设置开学日期" dialog kept)
   - versionName -> 6.4.0-r2.1, versionCode -> 531
   - the "去开通 / 去购买" buttons of the VIP dialogs no longer open the
     membership page (that page renders blank because the noads build has the
     online VIP/account routes disabled); the VIP gate itself is NOT touched.

usage: python build_r21.py --base-apk <r2.apk> --out <out.apk> [--workdir <dir>]
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WORK = r'E:\code\.dsh-mumu\work'
sys.path.insert(0, WORK)

import axml_patch                      # noqa: E402
import wakeup_jxust_fix as wjf         # noqa: E402

BUY_LISTENERS = [
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule\o0Oo0oo.smali'),              # 夜间模式
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule\o0O0OO0.smali'),              # 简洁模式
    ('classes6', r'com\suda\yzune\wakeupschedule\schedule_settings\o000oOoO.smali'),    # 课表设置-样式
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0O00000.smali'),                 # 会员页 去开通
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0oOOo.smali'),                   # 会员页 去购买
    ('classes5', r'com\suda\yzune\wakeupschedule\mine\o0O000o0.smali'),                 # 会员页 去购买
]

NOOP = '    return-void\n'

# 说明：曾经尝试过把「夜间模式 / 简洁模式」两个磁贴从「…」面板里彻底移除
# （把 o000O0Oo 里对应的两次 addView 改成 nop）。该改动已按用户要求回退，
# 本脚本不再包含它；如需恢复请参考 git 历史 / README 第 10 节的说明。


def noop_onclick(path):
    """Replace the body of onClick(View) in a synthetic listener with a no-op."""
    text = wjf.read(path)
    m = wjf.method_span(text, r'(?m)^\.method public final onClick\(Landroid/view/View;\)V')
    if not m:
        return False
    if NOOP.strip() in text[m[0]:m[1]] and 'invoke-' not in text[m[0]:m[1]].split('return-void')[0]:
        return False
    off = wjf.first_instruction_offset(text, m)
    if off is None:
        return False
    line_end = text.find('\n', off)
    wjf.write(path, text[:off] + '    return-void' + text[line_end:])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workdir', default=os.path.join(WORK, 'r21'))
    ap.add_argument('--baksmali', default=os.path.join(WORK, '..', 'tools', 'baksmali.jar'))
    ap.add_argument('--smali', default=os.path.join(WORK, '..', 'tools', 'smali.jar'))
    ap.add_argument('--signer', default=os.path.join(WORK, '..', 'tools', 'uber-apk-signer.jar'))
    ap.add_argument('--keystore', default=r'E:\code\wakeup-jxust-fix\keystore\wakeup-jxust.jks')
    ap.add_argument('--ks-alias', default='wakeupjxust')
    ap.add_argument('--ks-pass', default='wakeupjxust')
    args = ap.parse_args()

    work = os.path.abspath(args.workdir)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    dexdir = os.path.join(work, 'dex')
    os.makedirs(dexdir, exist_ok=True)

    trees = {}
    for dex in ('classes5.dex', 'classes6.dex'):
        with zipfile.ZipFile(args.base_apk) as z:
            open(os.path.join(dexdir, dex), 'wb').write(z.read(dex))
        tree = os.path.join(work, dex.replace('.dex', ''))
        subprocess.run([wjf.__dict__.get('JAVA', 'java'), '-Xmx2g', '-jar', args.baksmali,
                        'd', os.path.join(dexdir, dex), '-o', tree], check=True)
        trees[dex] = tree

    print('== 江苏科技大学导入修复 + 导入后提示精简')
    for dex in trees:
        p = os.path.join(trees[dex], 'com', 'suda', 'yzune', 'wakeupschedule', 'aaa', 'utils',
                         'o00O0000.smali')
        if os.path.exists(p):
            wjf.revert_short_circuits(p, dex)
    imp = os.path.join(trees['classes6.dex'], 'com', 'suda', 'yzune', 'wakeupschedule', 'schedule_import')
    wjf.write(os.path.join(imp, 'JxustFix.smali'), wjf.JXUST_FIX_SMALI)
    print('  [ok] JxustFix.smali')
    wjf.patch_login_activity(os.path.join(imp, 'LoginWebActivity.smali'))
    sch = os.path.join(trees['classes6.dex'], 'com', 'suda', 'yzune', 'wakeupschedule', 'schedule')
    wjf.patch_import_banner(os.path.join(sch, 'SchedulePullDownLayout.smali'))
    wjf.patch_import_tip_dialog(os.path.join(sch, 'ScheduleFragment$handleIntent$1.smali'))

    print('== VIP 弹窗不再跳转空白会员页（不改变 VIP 权益本身）')
    by_short = {k.replace('.dex', ''): v for k, v in trees.items()}
    for dex, rel in BUY_LISTENERS:
        p = os.path.join(by_short[dex], rel)

        if not os.path.exists(p):
            print('  [skip] missing', rel)
            continue
        print('  [%s] %s' % ('ok' if noop_onclick(p) else 'skip', rel.split('\\')[-1]))

    dex_map = {}
    for dex, tree in trees.items():
        out_dex = os.path.join(work, 'patched-' + dex)
        subprocess.run(['java', '-Xmx4g', '-jar', args.smali, 'a', tree, '-o', out_dex], check=True)
        dex_map[dex] = out_dex

    print('== 修改 AndroidManifest：versionName 6.4.0-r2.1 / versionCode 531')
    axml_src = os.path.join(work, 'AndroidManifest.orig.xml')
    axml_out = os.path.join(work, 'AndroidManifest.xml')
    with zipfile.ZipFile(args.base_apk) as z:
        open(axml_src, 'wb').write(z.read('AndroidManifest.xml'))
    subprocess.run([sys.executable, '-X', 'utf8', os.path.join(WORK, 'axml_patch.py'), args.base_apk,
                    axml_out, '--set-string', '6.4.0', '6.4.0-r2.1',
                    '--set-int', 'versionCode', '531'], check=True)
    dex_map['AndroidManifest.xml'] = axml_out

    unsigned = os.path.join(work, 'wakeup-r21-unsigned.apk')
    wjf.rebuild_apk(args.base_apk, unsigned, dex_map)

    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(outdir, '_signed')
    shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(['java', '-jar', args.signer, '-a', unsigned, '-o', tmp, '--skipZipAlign',
                    '--ks', args.keystore, '--ksAlias', args.ks_alias,
                    '--ksPass', args.ks_pass, '--ksKeyPass', args.ks_pass], check=True)
    produced = [f for f in os.listdir(tmp) if f.endswith('.apk')]
    shutil.move(os.path.join(tmp, produced[0]), args.out)
    shutil.rmtree(tmp, ignore_errors=True)
    print('signed apk:', args.out)


if __name__ == '__main__':
    main()
