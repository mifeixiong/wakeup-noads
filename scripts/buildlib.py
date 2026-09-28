"""构建公共库（buildlib）

针对 PR 审核意见做的加固：
  P1-1 凭据：keystore / 别名 / 口令一律不写默认值，按 CLI → 环境变量 → 受保护 env 文件
       → 交互输入（仅 TTY）的顺序解析；命令回显与日志里口令一律打码。
  P1-2 路径：所有默认路径都相对本仓库（tools/、scripts/），可在干净克隆里直接构建。
  P1-3 工作目录：默认使用临时目录；显式传入时做危险路径检查，且只清理本工具标记过的内容。
  P1-4 反编译缓存：smali 树带输入指纹（APK SHA + dex SHA + baksmali SHA），不匹配就重建。
  P2-5 补丁：required 锚点缺失即失败退出；optional 缺失记 WARN 并写入报告；
       每个替换要求"恰好命中一次"；补丁后回读校验关键改动确实在产物里。
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKDIR_MARKER = '.wakeup-build-workdir'
ENV_FILE = REPO_ROOT / '.signing.env'
TOOLS_DIR = REPO_ROOT / 'tools'


class BuildError(RuntimeError):
    """构建期错误：一律让调用方以非 0 退出。"""


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], *, quiet_value_flags=('--ksPass', '--ksKeyPass', '--ks-pass',
                                              '--ks-key-pass')) -> None:
    """执行外部命令；日志里对口令类参数打码，输出不截断。"""
    log('+ ' + mask_cmd(cmd, quiet_value_flags))
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.stdout:
        print(p.stdout.rstrip(), flush=True)
    if p.stderr:
        print(p.stderr.rstrip(), file=sys.stderr, flush=True)
    if p.returncode != 0:
        raise BuildError(f'命令失败（exit {p.returncode}）: {mask_cmd(cmd, quiet_value_flags)}')


def mask_cmd(cmd: list[str], value_flags=('--ksPass', '--ksKeyPass')) -> str:
    out, skip = [], False
    for i, c in enumerate(cmd):
        if skip:
            out.append('***')
            skip = False
            continue
        out.append(c)
        if c in value_flags:
            skip = True
    return ' '.join(out)


# --------------------------------------------------------------------------- #
# 工具 jar（默认取仓库内 tools/）
# --------------------------------------------------------------------------- #
def resolve_tools(tools_dir: str | Path | None = None) -> dict:
    d = Path(tools_dir) if tools_dir else TOOLS_DIR
    tools = {
        'baksmali': d / 'baksmali.jar',
        'smali': d / 'smali.jar',
        'signer': d / 'uber-apk-signer.jar',
    }
    missing = [str(p) for p in tools.values() if not p.exists()]
    if missing:
        raise BuildError(f'缺少构建工具（可用 --tools-dir 指定）：{missing}')
    return {k: str(v) for k, v in tools.items()}


# --------------------------------------------------------------------------- #
# P1-1 凭据
# --------------------------------------------------------------------------- #
@dataclass
class Signing:
    keystore: str
    alias: str
    password: str
    source: str

    def signer_args(self) -> list[str]:
        return ['--ks', self.keystore, '--ksAlias', self.alias,
                '--ksPass', self.password, '--ksKeyPass', self.password]


def _read_env_file(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def resolve_signing(keystore: str | None, alias: str | None, password: str | None,
                    env_file: str | Path | None = None, *, interactive: bool = True) -> Signing:
    """口令来源优先级：CLI → 环境变量 → env 文件 → 交互输入。绝不内置默认口令。"""
    env_path = Path(env_file) if env_file else ENV_FILE
    file_env = _read_env_file(env_path)
    keystore = keystore or os.environ.get('WAKEUP_KEYSTORE') or file_env.get('KEYSTORE')
    alias = alias or os.environ.get('WAKEUP_KS_ALIAS') or file_env.get('KS_ALIAS')
    password = password or os.environ.get('WAKEUP_KS_PASS') or file_env.get('KS_PASS')

    src = []
    if keystore:
        src.append('keystore')
    if not keystore:
        raise BuildError('缺少签名 keystore：用 --keystore 或环境变量 WAKEUP_KEYSTORE 指定'
                         f'（也可写进 {env_path} 的 KEYSTORE=…）')
    if not Path(keystore).exists():
        raise BuildError(f'keystore 不存在: {keystore}')
    if not alias:
        raise BuildError('缺少 keystore 别名：用 --ks-alias 或环境变量 WAKEUP_KS_ALIAS 指定')
    if not password:
        if interactive and sys.stdin.isatty():
            password = getpass.getpass(f'keystore 口令（{Path(keystore).name} / {alias}）: ')
            src.append('交互输入')
        else:
            raise BuildError('缺少 keystore 口令：用 --ks-pass、环境变量 WAKEUP_KS_PASS，'
                             f'或写进 {env_path} 的 KS_PASS=…（非交互环境不会自动尝试默认口令）')
    elif os.environ.get('WAKEUP_KS_PASS') == password:
        src.append('环境变量')
    elif file_env.get('KS_PASS') == password:
        src.append(f'env 文件 {env_path.name}')
    else:
        src.append('CLI 参数')
    return Signing(str(keystore), alias, password, '+'.join(src))


# --------------------------------------------------------------------------- #
# P1-3 工作目录
# --------------------------------------------------------------------------- #
DANGEROUS = {Path.home().resolve(), Path.cwd().resolve(), REPO_ROOT.resolve(),
             REPO_ROOT.resolve().parent}


def prepare_workdir(explicit: str | None = None, *, keep: bool = False) -> Path:
    """返回一个可安全清理的工作目录。

    * 未显式指定 → 在系统临时目录里新建（构建结束可删，绝不碰用户目录）；
    * 显式指定 → 拒绝盘符根/用户目录/仓库根及其父目录；目录非空且没有本工具标记时拒绝清理；
      只删除本工具已知的中间产物，不 rm -rf 整个目录。
    """
    if not explicit:
        work = Path(tempfile.mkdtemp(prefix='wakeup-build-'))
        (work / WORKDIR_MARKER).write_text('temporary workdir\n', encoding='utf-8')
        return work

    work = Path(explicit).expanduser().resolve()
    if work.parent == work:
        raise BuildError(f'拒绝使用盘符根作为工作目录: {work}')
    if work in DANGEROUS:
        raise BuildError(f'拒绝使用危险路径作为工作目录: {work}')
    if len(work.parts) < 3:
        raise BuildError(f'工作目录层级过浅，拒绝使用: {work}')
    marker = work / WORKDIR_MARKER
    if work.exists() and any(work.iterdir()) and not marker.exists():
        raise BuildError(f'{work} 非空且不是本工具创建的工作目录（缺少 {WORKDIR_MARKER}）；'
                         '请换一个空目录，或先手动确认内容')
    work.mkdir(parents=True, exist_ok=True)
    marker.write_text('managed by wakeup_jxust_fix build scripts\n', encoding='utf-8')
    return work


def clean_workdir(work: Path, *, keep: bool) -> None:
    if keep:
        log(f'保留工作目录: {work}')
        return
    if (work / WORKDIR_MARKER).exists() and (Path(tempfile.gettempdir()) in work.parents
                                             or work.parent == Path(tempfile.gettempdir())):
        shutil.rmtree(work, ignore_errors=True)
        log(f'已删除临时工作目录: {work}')
    else:
        log(f'工作目录保留（非临时目录，不自动删除）: {work}')


# --------------------------------------------------------------------------- #
# P1-4 反编译（带输入指纹，杜绝旧缓存混入产物）
# --------------------------------------------------------------------------- #
@dataclass
class DexTree:
    dex: str
    tree: Path
    reused: bool
    fingerprint: dict


def extract_dex(base_apk: str | Path, dex: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / dex
    with zipfile.ZipFile(base_apk) as z:
        names = set(z.namelist())
        if dex not in names:
            raise BuildError(f'{base_apk} 里没有 {dex}')
        data = z.read(dex)
    out.write_bytes(data)
    return out


def baksmali_dex(java: str, baksmali_jar: str, dex_path: Path, tree: Path,
                 base_apk_fp: str, *, force: bool = False) -> DexTree:
    fp = {
        'dex': dex_path.name,
        'dex_sha256': sha256_file(dex_path),
        'base_apk_sha256': base_apk_fp,
        'baksmali_sha256': sha256_file(baksmali_jar),
    }
    fp_file = tree / '.source.json'
    if not force and fp_file.exists():
        try:
            old = json.loads(fp_file.read_text(encoding='utf-8'))
        except Exception:
            old = None
        if old == fp:
            log(f'  [cache] {dex_path.name} 复用已反编译树（指纹一致）')
            return DexTree(dex_path.name, tree, True, fp)
        log(f'  [cache] {dex_path.name} 指纹不匹配，重建 smali 树')
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True, exist_ok=True)
    run([java, '-Xmx2g', '-jar', baksmali_jar, 'd', str(dex_path), '-o', str(tree)])
    if not any(tree.rglob('*.smali')):
        raise BuildError(f'{dex_path.name} 反编译后没有任何 .smali，输入 APK 可能不完整')
    fp_file.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding='utf-8')
    return DexTree(dex_path.name, tree, False, fp)


# --------------------------------------------------------------------------- #
# P2-5 补丁：必需/可选 + 恰好命中一次 + 报告
# --------------------------------------------------------------------------- #
class PatchError(BuildError):
    pass


@dataclass
class PatchRecorder:
    entries: list = field(default_factory=list)

    def add(self, name: str, *, required: bool, status: str, detail: str = '') -> None:
        self.entries.append({'name': name, 'required': required, 'status': status,
                             'detail': detail})
        tag = {'ok': 'ok   ', 'skip': 'skip ', 'warn': 'WARN ', 'fail': 'FAIL '}[status]
        log(f'  [{tag}] {name}{"（必需）" if required else "（可选）"}'
            + (f': {detail}' if detail else ''))

    @property
    def failed_required(self) -> list:
        return [e for e in self.entries if e['required'] and e['status'] != 'ok']

    def summary(self) -> dict:
        return {
            'total': len(self.entries),
            'ok': sum(1 for e in self.entries if e['status'] == 'ok'),
            'warn': sum(1 for e in self.entries if e['status'] == 'warn'),
            'skip': sum(1 for e in self.entries if e['status'] == 'skip'),
            'entries': self.entries,
        }


def substitute_once(text: str, old: str, new: str, *, name: str, required: bool,
                    rec: PatchRecorder, allow_already: bool = False) -> str:
    """替换一次并要求"恰好命中一次"：0 次按 required 决定失败/告警，>1 次一律失败。"""
    n = text.count(old)
    if n == 1:
        rec.add(name, required=required, status='ok')
        return text.replace(old, new, 1)
    if n == 0 and allow_already and new in text:
        rec.add(name, required=required, status='skip', detail='补丁已存在')
        return text
    if n == 0:
        if required:
            rec.add(name, required=True, status='fail', detail='锚点未找到')
            raise PatchError(f'必需补丁的锚点未找到: {name}')
        rec.add(name, required=False, status='warn', detail='锚点未找到，跳过')
        return text
    rec.add(name, required=required, status='fail', detail=f'锚点命中 {n} 次（应为 1 次）')
    raise PatchError(f'补丁锚点不唯一（{n} 次）: {name}')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PatchError(message)


def assert_patched(path: Path, patterns: list[tuple[str, bool]], *, rec: PatchRecorder) -> None:
    """补丁后回读校验：确认声明的改动确实落在产物里（防"静默产包"）。"""
    text = path.read_text(encoding='utf-8')
    for pat, required in patterns:
        if re.search(pat, text, re.M):
            rec.add(f'verify {path.name} :: {pat[:40]}', required=required, status='ok')
        elif required:
            rec.add(f'verify {path.name} :: {pat[:40]}', required=True, status='fail',
                    detail='产物里找不到该改动')
            raise PatchError(f'{path.name} 缺少必需改动: {pat}')
        else:
            rec.add(f'verify {path.name} :: {pat[:40]}', required=False, status='warn',
                    detail='产物里找不到该改动')


# --------------------------------------------------------------------------- #
# 重打包 / 签名
# --------------------------------------------------------------------------- #
def rebuild_apk(src_apk: str | Path, dst_apk: Path, replacements: dict[str, Path]) -> None:
    """按原 zip 布局重打包；resources.arsc 保持 STORED 且 4 字节对齐。"""
    src = zipfile.ZipFile(src_apk)
    if dst_apk.exists():
        dst_apk.unlink()
    dst = zipfile.ZipFile(dst_apk, 'w', zipfile.ZIP_DEFLATED)
    replaced = dropped = 0
    try:
        for info in src.infolist():
            name = info.filename
            if name.startswith('META-INF/') and (name.upper().endswith(
                    ('.SF', '.RSA', '.DSA', '.EC')) or name == 'META-INF/MANIFEST.MF'):
                dropped += 1
                continue
            data = replacements[name].read_bytes() if name in replacements else src.read(name)
            if name in replacements:
                replaced += 1
            zi = zipfile.ZipInfo(name, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            extra = b''
            if info.compress_type == zipfile.ZIP_STORED:
                misalign = (dst.fp.tell() + 30 + len(name.encode('utf-8'))) % 4
                if misalign:
                    length = 4 + (4 - misalign) % 4
                    extra = (0xD935).to_bytes(2, 'little') + (length - 4).to_bytes(2, 'little') \
                        + b'\x00' * (length - 4)
            zi.extra = extra
            dst.writestr(zi, data)
    finally:
        dst.close()
        src.close()
    log(f'  replaced entries: {replaced}, dropped signature files: {dropped}')


def sign_apk(java: str, signer_jar: str, unsigned: Path, out: Path, signing: Signing) -> None:
    tmp = out.parent / '_signed'
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        run([java, '-jar', signer_jar, '-a', str(unsigned), '-o', str(tmp), '--skipZipAlign',
             *signing.signer_args()])
        produced = [f for f in os.listdir(tmp) if f.endswith('.apk')]
        if not produced:
            raise BuildError('签名器没有产出 APK')
        shutil.move(str(tmp / produced[0]), str(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f'构建报告: {path}')
