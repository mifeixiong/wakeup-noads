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

修复
----
1) 让江苏科技大学改走 App 自带的正方（zf）解析器：导入时抓取「当前网页」的 HTML
   并用本地 ZFSuperParser 解析，全程不访问 WakeUp 服务端。
   实现：新增 JxustFix.apply()，在 LoginWebActivity.onCreate() 读取完 intent 之后
   钩一次；命中学校名时把 ViewModel 的导入类型字段改为 zf / wakeup。
2) 顺带关闭导入成功后不必要的打扰性 UI（顶部「导课成功」提示条、导入后「温馨提示」
   弹窗），保留含「设置开学日期」按钮的对话框。
3) 若目标版本仍带有 wakeup-noads 精简补丁注入的「账号/会话只读方法提前返回」，
   一并撤销（与上游 6.4.0-r1-issue3 的修复一致）。

用法
----
  python wakeup_jxust_fix.py --base-apk <wakeup-noads.apk> \
      --baksmali baksmali.jar --smali smali.jar \
      --signer uber-apk-signer.jar --keystore my.jks \
      --out wakeup-noads-jxustfix.apk
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

JXUST = '\u6c5f\u82cf\u79d1\u6280\u5927\u5b66'          # 江苏科技大学
WENXIN = '\u6e29\u99a8\u63d0\u793a'                     # 温馨提示 (dialog title)
DIALOG_CLASS = 'Lo00oOOO0/Oooo000;'                     # AlertDialog builder used by the tip
IMPORT_VM = 'Lcom/suda/yzune/wakeupschedule/schedule_import/ImportViewModel;'
LOGIN_ACT = 'Lcom/suda/yzune/wakeupschedule/schedule_import/LoginWebActivity;'

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

    iput-object v1, v0, %(vm)s->OooO0o0:Ljava/lang/String;

    const-string v1, "wakeup"

    iput-object v1, v0, %(vm)s->OooO0Oo:Ljava/lang/String;

    :cond_end
    return-void
.end method
''' % {
    'login_act': LOGIN_ACT,
    'vm': IMPORT_VM,
    'school': ''.join('\\u%04x' % ord(c) for c in JXUST),
}

SIG_SUFFIX = ('.SF', '.RSA', '.DSA', '.EC')


def log(msg):
    print(msg, flush=True)


def run(cmd):
    log('+ ' + ' '.join(cmd))
    subprocess.run(cmd, check=True)


# --------------------------------------------------------------------------- #
# smali text helpers
# --------------------------------------------------------------------------- #
def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def write(p, s):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(s)


def method_span(text, header_regex):
    """Return (start, end) character offsets of the method matching header_regex."""
    m = re.search(header_regex, text)
    if not m:
        return None
    end = text.find('\n.end method', m.start())
    return (m.start(), end if end != -1 else len(text))


def first_instruction_offset(text, span):
    """Offset of the first instruction line inside a method body
    (skips directives, annotation blocks and blank lines)."""
    start = span[0]
    pos = text.find('\n', start) + 1
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


def revert_short_circuits(path, label):
    """Remove 'const ...; return' early returns injected by the de-ad patch."""
    text = read(path)
    out = []
    reverted = 0
    for m in re.finditer(r'(?m)^\.method\b[^\n]*\n', text):
        pass
    # operate method by method
    result = text
    for m in list(re.finditer(r'(?m)^\.method\b[^\n]*\n', text))[::-1]:
        start = m.start()
        end = text.find('\n.end method', start)
        body = text[start:end]
        lines = body.split('\n')
        # locate first instruction index
        idx = None
        for i, l in enumerate(lines):
            s = l.strip()
            if s and not s.startswith('.') and not s.startswith('#'):
                idx = i
                break
        if idx is None or idx + 1 >= len(lines):
            continue
        const, ret = lines[idx].strip(), lines[idx + 1].strip()
        if re.match(r'^const(-string|/4|/16)?\s', const) and re.match(r'^return(-object|-void|-wide)?\b', ret):
            # 仅处理「后面还有真实代码」的方法（注入式短路会留下死代码）
            rest = [l for l in lines[idx + 2:] if l.strip() and not l.strip().startswith('.')]
            if not rest:
                continue
            del lines[idx:idx + 2]
            while idx < len(lines) and not lines[idx].strip():
                del lines[idx]
            new_body = '\n'.join(lines)
            result = result[:start] + new_body + result[end:]
            reverted += 1
    if reverted:
        write(path, result)
    log(f'  [{label}] reverted injected early returns: {reverted}')
    return reverted


def patch_login_activity(path):
    text = read(path)
    if 'JxustFix;->apply(' in text:
        log('  [LoginWebActivity] already patched')
        return
    anchor = 'invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;'
    gen = 'getExtras()Landroid/os/Bundle;'
    # 找到 school_name 之后、第一次取 intent extras 之前的位置
    school = text.find('const-string v2, "school_name"')
    if school == -1:
        school = text.find('"school_name"')
    pos = text.find(anchor, school if school != -1 else 0)
    while pos != -1 and gen not in text[pos:pos + 400]:
        pos = text.find(anchor, pos + 1)
    if pos == -1:
        sys.exit('ERROR: LoginWebActivity anchor not found')
    # 插到该锚点前（保持 label/缩进）
    insert = ('    invoke-static {p0}, Lcom/suda/yzune/wakeupschedule/schedule_import/'
              'JxustFix;->apply(Lcom/suda/yzune/wakeupschedule/schedule_import/LoginWebActivity;)V\n\n')
    write(path, text[:pos] + insert + text[pos:])
    log('  [LoginWebActivity] JxustFix hook injected')


def patch_import_banner(path):
    """SchedulePullDownLayout.showImportFeedback(...) -> no-op."""
    text = read(path)
    span = method_span(text, r'(?m)^\.method public final showImportFeedback\(')
    if not span:
        log('  [SchedulePullDownLayout] showImportFeedback not found (skip)')
        return
    if 'return-void' in text[span[0]:first_instruction_offset(text, span) or span[0]]:
        log('  [SchedulePullDownLayout] already patched')
        return
    off = first_instruction_offset(text, span)
    if off is None:
        sys.exit('ERROR: cannot locate first instruction of showImportFeedback')
    line_end = text.find('\n', off)
    write(path, text[:off] + '    return-void' + text[line_end:])
    log('  [SchedulePullDownLayout] import banner disabled')


def patch_import_tip_dialog(path):
    """ScheduleFragment$handleIntent$1 -> skip the 温馨提示 dialog."""
    text = read(path)
    if '\\u6e29\\u99a8\\u63d0\\u793a' not in text:
        log('  [ScheduleFragment$handleIntent$1] tip dialog not found (skip)')
        return
    rx = re.compile(
        r'(?m)^([ \t]*)if-eqz ([pv]\d+), (:\w+)((?:[ \t]*\n(?:[ \t]*\.line \d+)?)*)\n[ \t]*new-instance \w+, '
        + re.escape(DIALOG_CLASS))
    m = rx.search(text)
    if not m:
        log('  [ScheduleFragment$handleIntent$1] guard pattern not found (skip)')
        return
    write(path, text[:m.start()] + m.group(1) + 'goto ' + m.group(3) + m.group(4) + text[m.end():])
    log('  [ScheduleFragment$handleIntent$1] tip dialog disabled')


# --------------------------------------------------------------------------- #
# apk rebuild / sign
# --------------------------------------------------------------------------- #
def rebuild_apk(src_apk, dst_apk, dex_map):
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
        data = open(dex_map[name], 'rb').read() if name in dex_map else src.read(name)
        replaced += 1 if name in dex_map else 0
        zi = zipfile.ZipInfo(name, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zi.internal_attr = info.internal_attr
        zi.create_system = info.create_system
        extra = b''
        if info.compress_type == zipfile.ZIP_STORED:
            misalign = (dst.fp.tell() + 30 + len(name.encode('utf-8'))) % 4
            if misalign:
                need = (4 - misalign) % 4
                length = 4 + need
                extra = (0xD935).to_bytes(2, 'little') + (length - 4).to_bytes(2, 'little') + b'\x00' * (length - 4)
        zi.extra = extra
        dst.writestr(zi, data)
    dst.close()
    src.close()
    log(f'  replaced dex: {replaced}, dropped signature entries: {dropped}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--baksmali', required=True)
    ap.add_argument('--smali', required=True)
    ap.add_argument('--signer', required=True)
    ap.add_argument('--keystore', required=True)
    ap.add_argument('--ks-alias', default='wakeupjxust')
    ap.add_argument('--ks-pass', default='wakeupjxust')
    ap.add_argument('--out', required=True)
    ap.add_argument('--workdir', default='build')
    ap.add_argument('--java', default='java')
    ap.add_argument('--dexes', nargs='*', default=['classes5.dex', 'classes6.dex'])
    args = ap.parse_args()

    work = os.path.abspath(args.workdir)
    dexdir = os.path.join(work, 'dex')
    os.makedirs(dexdir, exist_ok=True)

    trees = {}
    for dex in args.dexes:
        with zipfile.ZipFile(args.base_apk) as z:
            open(os.path.join(dexdir, dex), 'wb').write(z.read(dex))
        tree = os.path.join(work, dex.replace('.dex', ''))
        if not os.path.isdir(tree):
            run([args.java, '-Xmx2g', '-jar', args.baksmali, 'd', os.path.join(dexdir, dex), '-o', tree])
        trees[dex] = tree

    log('applying patches')
    pkg = os.path.join('com', 'suda', 'yzune', 'wakeupschedule')

    # 1. 会话只读方法（旧版精简补丁可能会短路）
    for dex in args.dexes:
        p = os.path.join(trees[dex], pkg, 'aaa', 'utils', 'o00O0000.smali')
        if os.path.exists(p):
            revert_short_circuits(p, os.path.basename(p))

    # 2. 江苏科技大学 -> 内置正方解析器
    tree6 = trees.get('classes6.dex')
    if not tree6:
        sys.exit('ERROR: classes6.dex is required')
    imp = os.path.join(tree6, pkg, 'schedule_import')
    if not os.path.isdir(imp):
        sys.exit('ERROR: schedule_import package not found in classes6')
    write(os.path.join(imp, 'JxustFix.smali'), JXUST_FIX_SMALI)
    log('  [schedule_import] JxustFix.smali added')
    patch_login_activity(os.path.join(imp, 'LoginWebActivity.smali'))

    # 3. 导入后的打扰性 UI
    sch = os.path.join(tree6, pkg, 'schedule')
    patch_import_banner(os.path.join(sch, 'SchedulePullDownLayout.smali'))
    patch_import_tip_dialog(os.path.join(sch, 'ScheduleFragment$handleIntent$1.smali'))

    # 4. 回编 + 重打包 + 签名
    dex_map = {}
    for dex, tree in trees.items():
        out_dex = os.path.join(work, 'patched-' + dex)
        run([args.java, '-Xmx4g', '-jar', args.smali, 'a', tree, '-o', out_dex])
        dex_map[dex] = out_dex

    unsigned = os.path.join(work, 'wakeup-jxust-unsigned.apk')
    rebuild_apk(args.base_apk, unsigned, dex_map)

    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(outdir, '_signed')
    shutil.rmtree(tmp, ignore_errors=True)
    run([args.java, '-jar', args.signer, '-a', unsigned, '-o', tmp, '--skipZipAlign',
         '--ks', args.keystore, '--ksAlias', args.ks_alias,
         '--ksPass', args.ks_pass, '--ksKeyPass', args.ks_pass])
    produced = [f for f in os.listdir(tmp) if f.endswith('.apk')]
    if not produced:
        sys.exit('ERROR: signer produced no apk')
    shutil.move(os.path.join(tmp, produced[0]), args.out)
    shutil.rmtree(tmp, ignore_errors=True)
    log('signed apk: ' + args.out)


if __name__ == '__main__':
    main()
