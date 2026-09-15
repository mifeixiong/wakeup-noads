# 江苏科技大学（正方教务）课表导入失败 —— 根因与修复方案

> 关联 Issue：[#2](../../issues/2)、[#3](../../issues/3)
> 适用版本：`wakeup-noads` 6.3.0（r1~r4）与 6.4.0（r1/r2）等以 `importType=ziyan`
> 方式导入江苏科技大学的构建
> 修复脚本：[`scripts/wakeup_jxust_fix.py`](../scripts/wakeup_jxust_fix.py)
> 验证环境：MuMu 模拟器（Android 12，x86_64 + Houdini），应用包名 `com.suda.yzune.wakeupschedule`

## 1. 现象

选择「江苏科技大学」→ 打开教务系统 → 登录后进入「个人课表查询」（页面已显示课表）
→ 点右下角导入按钮，固定失败：

```
导入失败>_<请认真看一下提示。此页面似乎没有课程信息。
详细的错误信息如下：
com.android.volley.ResponseContentError
```

同一个学校在官方（带广告）版本上可以导入成功。

## 2. 根因

### 2.1 该学校走的是「服务端脚本」导入通道

学校在列表中的配置（应用保存在 `shared_prefs/config.xml` 的 `import_school`）：

```json
{"importType":"ziyan","type":"zf","name":"江苏科技大学",
 "url":"https://client.v.just.edu.cn/https/webvpn764a2e4853ae5e537560ba711c0f46bd/"}
```

`importType=ziyan` 时 `LoginWebActivity` 会使用 `DXParserLoginFragment`：导入前先通过
`EncryptNet` 向服务端请求一份动态解析脚本（`ScriptEnpluginBean` →
`/wakeup/script/enplugin`，参数 `name=wakeup_schedule_inject_script&type=wakeup_schedule`），
再把脚本注入 WebView 执行解析。也就是说：**只要这条加密请求失败，导入必然失败，
和教务页面本身没有关系**。

### 2.2 这条加密请求在部分环境下必然失败

在 x86 模拟器上，每次点导入 logcat 都会出现：

```
W/System.err: java.lang.ArrayIndexOutOfBoundsException: length=0; index=0
    at o00o0O.o0OO00O.OooO0o0(SourceFile:30)
    at com.suda.yzune.wakeupschedule.aaa.utils.oOO00O.OooO0oo(SourceFile:14)
    at com.suda.yzune.wakeupschedule.aaa.utils.EncryptNet.OooO0o0(SourceFile:21)
    at com.suda.yzune.wakeupschedule.aaa.utils.EncryptNet$buildEncryptInput$1.invokeSuspend(SourceFile:30)
```

反编译还原出的调用链：

- `EncryptNet.OooO0o0()` → `oOO00O.OooO0OO(参数)`，即 RC4 加密请求体；
- `oOO00O`（RC4Helper）的密钥来自
  `com.zuoyebang.baseutil.OooO00o.OooO0O0(String.valueOf(cuid))`；
- 而 `OooO00o.OooO0OO(String, boolean)` 中**只有 `isInitSuccess == true` 时才调用
  `NativeHelper.nativeGetKey()`**，否则返回空串；
- 密钥为空 → RC4 状态数组长度为 0 → `length=0; index=0`；
- 请求体加密失败 → 服务端返回非预期响应 → `com.android.volley.ResponseContentError`。

`libbaseutil.so` 只提供 `arm64-v8a`，在 x86/arm64 翻译层（Houdini）下其 Antispam
初始化不成功，因此该环境里**所有依赖 `EncryptNet` 的接口都不可用**。

### 2.3 另一处已知原因（上游 6.4.0-r1-issue3 已修复）

早期精简补丁把 `aaa/utils/o00O0000` 的账号/会话**只读**方法
（`ACCOUNT_DXUSS`、`ACCOUNT_USER_INFO`、会话有效性）短路成空值，导致动态脚本请求的
公共参数与 Cookie 链取不到，同样报 `ResponseContentError`。
6.4.0-r1-issue3 / r2 已恢复这三处实现；本脚本会在检测到该短路时自动撤销，
以便在仍带该回归的构建（例如 6.3.0 系列）上也能工作。

## 3. 修复方案

不再依赖服务端动态脚本，而是让江苏科技大学改走 **App 自带的「正方（zf）」解析器**：

1. 新增 `JxustFix.apply(LoginWebActivity)`：当 `school_name` 为「江苏科技大学」时，
   把 `ImportViewModel` 的导入类型直接置为 `zf` / `wakeup`
   （直接写字段 `OooO0o0` / `OooO0Oo`，字段名在各版本间稳定，不依赖混淆后的 setter 名）。
2. 在 `LoginWebActivity.onCreate()` 读完 intent 之后插入一次
   `JxustFix.apply(this)`；由于 `ziyan` 之外的类型一律走 `WebViewLoginFragment`，
   导入随即变成官方正方教务流程：

   ```
   登录教务 → 进入「个人课表查询」→ 点导入 → 注入 getPageHtml 抓取当前页面 HTML
           → ZFSuperParser 本地解析 → 写库
   ```

   全程**不访问 WakeUp 服务端**，因此不受上述加密链路故障影响；其它学校行为不变。
3. 顺带关闭导入成功后与课表无关的打扰性 UI（**保留**含「设置开学日期」的对话框）：
   - `SchedulePullDownLayout.showImportFeedback(...)`：顶部「导课成功 / 已导入 N 门课程…」提示条；
   - `ScheduleFragment$handleIntent$1`：导入后的「温馨提示」弹窗。

## 4. 验证结果

| 项目 | 6.3.0（r3/r4 基线） | 6.4.0-r2 |
| --- | --- | --- |
| 修复前 | 导入失败 `ResponseContentError` | 同左 |
| 修复后 | 导课成功，导入 10 门课程（17 条课程明细） | 导课成功，导入 10 门课程 |
| 顶部「导课成功」提示条 | 不再出现 | 不再出现 |
| 「导课成功 / 设置开学日期」对话框 | 保留 | 保留 |
| 日志 | 无 `ArrayIndexOutOfBounds` / `EncryptNet` / `ResponseContentError` | 同左 |

数据库核对（Room，`/data/data/com.suda.yzune.wakeupschedule/databases/wakeup`）：

```
TableBean         (2, 1, 0, '江苏科技大学', '<uuid>', <ts>)
CourseBaseBean    高等数学A1 / 大学英语1 / 马克思主义基本原理 / 船舶与海洋工程导论 /
                  国家安全教育 / 思想道德与法治 / 职业生涯发展规划 / 人工智能技术及应用 / …
CourseDetailBean  (周三, 长山校区 笃学楼-305, 李传贞, 第1-2节, 5-17周) …
```

## 5. 复现构建

```bash
# 依赖：JDK 11+、baksmali.jar、smali.jar、uber-apk-signer.jar、一个签名用 keystore
python scripts/wakeup_jxust_fix.py \
  --base-apk  wakeup-noads-v6.4.0-r2.apk \
  --baksmali  baksmali.jar \
  --smali     smali.jar \
  --signer    uber-apk-signer.jar \
  --keystore  my-release.jks --ks-alias myalias --ks-pass mypass \
  --out       wakeup-noads-v6.4.0-r2-jxustfix.apk
```

脚本按「方法名 / XPath 式锚点」定位代码（不依赖固定行号），因此对后续版本也适用；
若某个锚点在新版本中消失，脚本会明确提示 `anchor not found` 而不是产出坏包。

## 6. 备注

- 走内置正方解析器时，解析质量取决于 App 自带的 `ZFSuperParser`；导入后请自行核对。
  调课、停课信息不会被导入（App 原生行为）。
- 「设置开学日期」对话框只在新导入的课表还没有学期开始日期时出现，属官方行为。
- 江苏科技大学的教务系统需要通过学校 WebVPN 访问；本修复不修改任何学校地址，
  仍使用应用内登记的学校网址。
