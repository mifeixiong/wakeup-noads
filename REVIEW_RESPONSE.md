# PR 审核意见处理说明

对应审核提出的 5 条阻塞项，逐条给出**修法**与**可复核证据**。全部改动集中在 `buildlib.py`（新增）、
`wakeup_jxust_fix.py`、`build_r21.py`、`axml_patch.py`、`build_fixed_apk.py`。

## 1. 签名凭据泄露（P1）

**修法**

- 新增 `buildlib.resolve_signing()`：口令来源固定为 **CLI 参数 → 环境变量 → `仓库根/.signing.env`
  → 交互输入（仅 TTY）**，脚本里不再出现任何默认口令或默认别名。非交互环境下缺失口令直接失败，
  不会回落到硬编码值。
- 命令回显统一走 `buildlib.run()`：`--ksPass` / `--ksKeyPass` 的值一律打印成 `***`。
- **证书轮换**：旧 keystore（`keystore/wakeup-jxust.jks`，口令曾写进公开脚本）按"泄露"处理，
  已生成新 keystore `keystore/wakeup-jxust-v2.jks`（RSA 4096、有效期 30 年、28 位随机口令，
  口令只写进本地 `.signing.env`，该文件与 keystore 都不入库）。
- **三个分发产物全部用新证书重新签名**（r2.1 重新构建；r2 与 6.3.0 剥离旧签名后用新证书重签）。

**证据**

```
$ grep -rn "wakeupjxust" scripts/*.py          # 旧默认口令/别名已无任何命中
$ python scripts/build_r21.py ...              # 日志中：
  + java -jar tools/uber-apk-signer.jar ... --ksPass *** --ksKeyPass ***
$ keytool -printcert -jarfile dist/*.apk
  所有者: CN=WakeUp JXUST Fix v2, OU=Local Patch, O=Local, L=Local, ST=Local, C=CN
```

## 2. 构建不可复现、依赖作者本机路径（P1）

**修法**

- 所有默认路径改为相对脚本自身：`REPO_ROOT = Path(__file__).resolve().parents[1]`，工具 jar 默认取
  `仓库/tools/{baksmali,smali,uber-apk-signer}.jar`（可用 `--tools-dir` 覆盖）。
- `build_r21.py` 不再 `sys.path.insert` 作者机器的 `.dsh-mumu/work`，改为导入仓库内 `axml_patch.py`。
- `wakeup_jxust_fix.py` 的 `--baksmali/--smali/--signer` 不再是必填项（默认走仓库 `tools/`），
  keystore/别名/口令改为可选（走环境变量或 `.signing.env`）。

**证据**

```
$ grep -rn "E:\\\\code" scripts/ | wc -l      # 0
$ python scripts/build_r21.py --base-apk <apk> --out out.apk     # 干净克隆可用（只需 tools/ 与口令）
```

## 3. 危险的工作目录清理（P1）

**修法** `buildlib.prepare_workdir()` / `clean_workdir()`

- 未显式指定 `--workdir`：使用 `tempfile.mkdtemp()`，构建结束只删这个自己建的临时目录。
- 显式指定时：拒绝盘符根、用户主目录、仓库根及其父目录、层级过浅的路径；
  目标非空且**没有本工具标记文件** `.wakeup-build-workdir` 时直接拒绝，绝不 `rmtree` 别人的目录。
- 全程不再出现"无条件删除用户传入目录"的代码。

**证据**

```
$ python scripts/build_r21.py --workdir E:\ --out out.apk
构建失败: 拒绝使用盘符根作为工作目录: E:\
$ python scripts/build_r21.py --workdir E:\some\existing\dir --out out.apk
构建失败: … 非空且不是本工具创建的工作目录（缺少 .wakeup-build-workdir）…
```

## 4. 旧缓存可能污染产物（P1）

**修法** `buildlib.extract_dex()` / `baksmali_dex()`

- 每次构建都从**输入 APK** 现场抽取 dex（并校验该 dex 确实存在于 zip 内），不存在"复用上次 dex"的路径。
- smali 树内写入 `.source.json`：`{dex_sha256, base_apk_sha256, baksmali_sha256}`；只要与本次输入不一致
  就整树删除重建；`--force-recompile` 可强制重编译。
- 反编译后若没有任何 `.smali`，直接失败（防止把空树继续往下编）。

**证据**

```
$ python scripts/build_r21.py … --force-recompile   # 全量重建
$ python scripts/build_r21.py …                      # 命中缓存时日志：[cache] classes6.dex 复用已反编译树（指纹一致）
$ python scripts/build_r21.py --base-apk <另一个 apk> …  # 指纹变化 → [cache] 指纹不匹配，重建 smali 树
```

## 5. 补丁失败会静默跳过（P2）

**修法**

- `buildlib.PatchRecorder` + `substitute_once()`：每个替换都记录 `required/optional` 与命中次数；
  **必需锚点 0 次命中 → 记录 FAIL 并抛错、构建以非 0 退出**；命中 **>1 次** 也一律失败（锚点歧义）。
- `axml_patch.patch_manifest()`：字符串/整型属性的每一处修改都要求**恰好命中一次**，
  0 次或多次都报错；构建脚本再对产物回读校验 `versionName/versionCode`。
- 补丁后 `assert_patched()` 回读产物文本，确认声明的改动真的落地（例如 `LoginWebActivity` 里必须出现
  `JxustFix;->apply(`）。
- `--strict`：把可选补丁也当必需（CI 可用）。
- 构建结束输出 `dist/<apk>.build-report.json`：输入/输出 SHA-256、dex 指纹、manifest 改写命中数、
  每条补丁的状态。

**证据**（本机实测的构建报告摘要）

```
patches : total=17 ok=15 warn=1 skip=1
  skip  可选 恢复账号/会话只读方法（o00O0000） | 目标版本没有该短路
  warn  可选 恢复账号/会话只读方法（o00O0000） | o00O0000.smali 不存在
  ok    必需 ImportViewModel 字段 OooO0o0/OooO0Oo
  ok    必需 新增 schedule_import/JxustFix.smali
  ok    必需 verify LoginWebActivity.smali :: JxustFix 钩子
  ok    可选 关闭导入成功顶部提示条（showImportFeedback）
  ok    可选 关闭导入后「温馨提示」弹窗
  ok    可选 夜间模式/简洁模式/样式页「去开通」→取消
  ok    可选 会员页三个「去购买」保持空操作
  ok    必需 产物 versionName | 6.4.0-r2.1
  ok    必需 产物 versionCode | 531
  ok    必需 产物包含 classes5.dex / classes6.dex
axml : versionName hits=1（6.4.0 → 6.4.0-r2.1）；versionCode hits=1（530 → 531）
```

（1 条 warn + 1 条 skip 都是"目标版本本来就没有该短路"的正常情况；加 `--strict` 时脚本会因此失败，
不会静默产包。）

## 产物与校验

| 文件 | SHA-256 | 证书 |
| --- | --- | --- |
| `wakeup-noads-v6.4.0-r2.1-jxustfix.apk` | `EAC2250C13BD0A389D7D88C9FB127F0417FE3E86D2BA9B1914A9EF2DF715F047` | WakeUp JXUST Fix v2 |
| `wakeup-noads-v6.4.0-r2-jxustfix.apk` | `19E67EE68A661A172AE93DFC69B7AFD6B81166AE3169B3B0842DE09DFA59395B` | WakeUp JXUST Fix v2 |
| `wakeup-noads-6.3.0-jxustfix.apk` | `3CBF20593AE298E40490922189CFD2554984A2818826DDB7D3BA8D3E2D72E920` | WakeUp JXUST Fix v2 |

真机验证（MuMu 模拟器，Android 12 / x86_64）：新证书包卸载重装后跑完整导入场景
**37 步全绿**（`ok: true`），数据库 `TableBean 1→2`、`CourseBaseBean 0→11`、`CourseDetailBean 0→18`，
日志无 `ResponseContentError`。

> 旧证书签名的包（`0997E3A6…` / `FB7A362A…`）已作废，请使用上表的新哈希。
