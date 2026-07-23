# WakeUp 新版本精简维护手册

本文档用于在 WakeUp 课程表发布新版本后，快速重新完成去广告、移除学习/账户/云同步模块，并保留高校教务系统课表导入与本地课表功能。

最后更新：2026-07-23  
参考基线：WakeUp `6.2.05`（versionCode `485`）

> [!IMPORTANT]
> 新版本的 DEX、混淆类名、方法名、寄存器和资源 ID 都可能变化。迁移时应按业务语义和调用链重新定位，不能直接照抄旧版行号、标签或 Smali 寄存器。

## 1. 目标与边界

### 目标

- 关闭应用业务层的全部已知广告入口。
- 禁用广告 SDK 的 Manifest 组件和广告标识相关权限。
- 删除底部学习、搜题和关联助手页面。
- 关闭应用账户、会员、用户资料及云同步功能。
- 消除账户或云服务不可用引发的启动网络错误提示。
- 保留本地课表、学校列表、教务 Web 登录、课表解析和导入。
- 使用同一项目证书签名，保持精简版后续更新连续性。

### 必须保持不变的边界

- 保留包名 `com.suda.yzune.wakeupschedule`，除非明确决定制作共存包。
- 保留 `android.permission.INTERNET`。
- 不修改 `schedule_import` 和 `schedule_parser` 的业务实现。
- 不禁用 `SchoolListActivity`、`LoginWebActivity` 及高校导入路由。
- 不直接删除广告 SDK 类库；优先关闭入口和 Manifest 组件，避免类验证或混淆引用崩溃。
- 不将签名密钥、密钥密码、账号、Cookie 或 Token 提交到公开仓库。

## 2. 快速流程

每次更新按以下顺序执行：

1. 归档旧版最终 APK、报告、补丁和签名密钥。
2. 记录新版 APK 的版本、哈希、包名和原始证书。
3. 分别用 apktool 和 JADX 解包，另保留一份未修改对照目录。
4. 先确认高校导入目录和入口，再开始修改。
5. 迁移广告业务短路补丁。
6. 运行并复核广告 Manifest 组件禁用脚本。
7. 移除学习/助手底栏 Fragment。
8. 短路账户、用户资料、会员和登录 Action。
9. 短路课表与日历云同步入口。
10. 隐藏“我的”页相关控件并复核状态栏安全间距。
11. apktool 重建、zipalign 对齐、apksigner 签名。
12. 二次反编译最终签名 APK，执行静态验收。
13. 在真机完成启动、本地课表和高校导入回归测试。
14. 更新 README、Release Notes、哈希与维护报告。

## 3. 工具与目录

### 工具

当前任务使用过：

| 工具 | 参考版本 | 用途 | 获取来源 |
| --- | --- | --- | --- |
| JDK | 21 | 运行 apktool、生成和使用签名密钥 | [Azul Zulu](https://www.azul.com/downloads/) 或其他可信 OpenJDK 发行版 |
| apktool | 3.0.3 | 解码/重建资源、Manifest 和 Smali | [iBotPeaches/Apktool Releases](https://github.com/iBotPeaches/Apktool/releases) |
| JADX | 1.5.6 | 阅读接近 Java/Kotlin 语义的反编译代码 | [skylot/jadx Releases](https://github.com/skylot/jadx/releases) |
| Android build-tools | 34.0.0 | zipalign、apksigner | [Android SDK Build Tools](https://developer.android.com/tools/releases/build-tools) |
| Android platform-tools | 37.0.0 | ADB 真机安装、日志与回归测试 | [SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools) |
| ripgrep | 当前系统版本 | 快速检索类名、字符串和调用点 | [BurntSushi/ripgrep Releases](https://github.com/BurntSushi/ripgrep/releases) |

工具来源、下载校验和清理路径记录在 `apk_work/TOOL_INSTALLS.md`。

### 建议目录

```text
work/<version>/
|-- input/
|   `-- base.apk
|-- original_apktool/       # 原始对照，永不修改
|-- decoded/                # 实际补丁目录
|-- jadx/                   # 语义定位目录
|-- verify/                 # 最终签名 APK 二次反编译目录
|-- output/
|   |-- unsigned.apk
|   |-- aligned.apk
|   `-- signed.apk
`-- reports/
```

不要复用上一版本的 `decoded/build` 缓存作为新版本输入。

## 4. 建立新版基线

以下示例均在 PowerShell 中执行。变量名可按实际版本调整。

```powershell
$WakeupVersion = 'NEW_VERSION'
$WakeupInputApk = Resolve-Path '.\work\NEW_VERSION\input\base.apk'
$WakeupWork = Join-Path (Get-Location) "work\$WakeupVersion"
$WakeupOriginal = Join-Path $WakeupWork 'original_apktool'
$WakeupDecoded = Join-Path $WakeupWork 'decoded'
$WakeupJadx = Join-Path $WakeupWork 'jadx'
$WakeupVerify = Join-Path $WakeupWork 'verify'
$WakeupOutput = Join-Path $WakeupWork 'output'
$WakeupReports = Join-Path $WakeupWork 'reports'
New-Item -ItemType Directory -Force -Path $WakeupOutput, $WakeupReports | Out-Null
```

### 4.1 记录输入哈希

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath $WakeupInputApk
```

把哈希、文件大小、获取来源和日期写入本版本报告。

### 4.2 解码两份 apktool 工程

```powershell
java -jar '.\apk_work\tools\apktool.jar' d -f $WakeupInputApk -o $WakeupOriginal
java -jar '.\apk_work\tools\apktool.jar' d -f $WakeupInputApk -o $WakeupDecoded
```

`original_apktool` 仅用于对照和最终差异检查，任何补丁只写入 `decoded`。

### 4.3 生成 JADX 语义视图

```powershell
& '.\apk_work\tools\jadx\bin\jadx.bat' -d $WakeupJadx $WakeupInputApk
```

如果 JADX 局部反编译失败，仍以 Smali 为准；JADX 主要用于识别方法语义和调用链。

### 4.4 记录版本信息

检查 `$WakeupOriginal\apktool.yml` 中的：

- `minSdkVersion`
- `targetSdkVersion`
- `versionCode`
- `versionName`
- DEX 数量

同时确认最终包名仍为 `com.suda.yzune.wakeupschedule`。

## 5. 先冻结高校导入边界

修改前先记录以下目录和类的哈希或 Git no-index 差异基线：

```text
com/suda/yzune/wakeupschedule/schedule_import/
com/suda/yzune/wakeupschedule/schedule_parser/
com/suda/yzune/wakeupschedule/schedule_import/SchoolListActivity
com/suda/yzune/wakeupschedule/schedule_import/LoginWebActivity
com/suda/yzune/wakeupschedule/aaa/nativerouter/ImportFromEasRouter
```

检索入口：

```powershell
rg -n 'SchoolListActivity|LoginWebActivity|ImportFromEasRouter' $WakeupJadx
rg -n 'schedule_import|schedule_parser' (Join-Path $WakeupDecoded 'AndroidManifest.xml')
```

这些路径如果在新版被官方改动，应保留新版实现，而不是复制旧版文件覆盖。

## 6. 去广告补丁

采用三层处理：业务判断短路、广告页关闭、Manifest 组件禁用。

### 6.1 重新定位广告配置入口

优先检索稳定业务字符串，不依赖混淆类名：

```powershell
rg -n 'COLD_SPLASH_AD|HOT_SPLASH_AD|SCHEDULE_INSERT_AD|SCHEDULE_STREAM_AD|ADET_Norequest' $WakeupJadx
rg -n 'coldSplash|hotSplash|scheduleInsert|scheduleStream|flowAd' $WakeupJadx
```

6.2.05 参考类：

```text
com.suda.yzune.wakeupschedule.aaa.utils.OooOOOO
```

6.2.05 参考映射：

| 方法 | 语义 | 目标返回 |
| --- | --- | --- |
| `OooO00o()` | 热启动广告是否展示 | `false` |
| `OooO0O0()` | 课表插屏是否展示 | `false` |
| `OooO0OO()` | 冷启动广告是否展示 | `false` |
| `OooO0Oo()` | 拉取远端广告配置 | 立即 `return-void` |
| `OooO0o()` | 冷启动广告资源 ID | `0` |
| `OooO0o0()` | 热启动广告资源 ID | `0` |
| `OooO0oO()` | 插屏广告 ID | `0` |
| `OooO()` | 信息流广告 ID | `0` |
| `OooO0oo()` | 最终信息流广告位 | `-1` |

新版中方法名可能变化，应通过读取的 Preference、埋点字符串和返回类型确认。

常用 Smali 返回模板：

```smali
# boolean / int 关闭值
const/4 v0, 0x0
return v0
```

```smali
# 无效广告位
const/4 v0, -0x1
return v0
```

```smali
# void 方法
return-void
```

不要改变方法签名。新增返回指令前确认 `.locals` 至少有一个可用寄存器；没有寄存器时可直接使用参数寄存器或调整 `.locals`，但必须重新构建验证。

### 6.2 关闭热启动广告 Activity

检索：

```powershell
rg -n 'ResumeSplashActivity' $WakeupJadx $WakeupDecoded
```

6.2.05 中：

```text
com.suda.yzune.wakeupschedule.aaa.resume.ResumeSplashActivity
```

其广告加载方法 `o0Oo0oo()` 被处理为立即调用页面结束方法后返回。新版应确认真正的广告加载入口，避免只禁用回调而留下空白页。

同时在 Manifest 将该 Activity 设置为：

```xml
android:enabled="false"
```

### 6.3 禁用广告 Manifest 组件

当前脚本（可随仓库提交）：

```text
scripts/disable_ad_components.ps1
```

执行示例：

```powershell
& '.\scripts\disable_ad_components.ps1' `
  -ManifestPath (Join-Path $WakeupDecoded 'AndroidManifest.xml') `
  | Set-Content -Encoding utf8 (Join-Path $WakeupReports 'manifest_patch_report.json')
```

脚本中的厂商、组件和权限清单以 6.2.05 为基线。对新版执行前先阅读脚本并逐项复核；执行后必须检查生成的 JSON 报告和 Manifest 差异。

脚本当前匹配的主要命名空间包括：

- `com.fastad`
- `com.kwad`
- `com.qq.e`
- `com.byazt`
- `com.bytedance.sdk.openadsdk`
- `com.bytedance.msdk`
- `com.bytedance.android.openliveplugin`
- `com.byted.live.lite`
- `com.baidu.mobads`
- `com.baidu.oauth.sdkbqt`
- `com.component.patchad`

6.2.05 的结果是 149 个组件、12 条权限声明和 1 条元数据。这个数字仅是参考：

- 数量减少时，检查广告 SDK 是否改名或移除。
- 数量增加时，逐项确认没有误伤登录、导入、文件分享或系统服务。
- 出现新广告厂商时，先确认调用链，再扩充正则。
- 权限是否“仅广告使用”必须在新版重新检索，不能仅凭旧清单删除。

必须确认 `android.permission.INTERNET` 仍存在。

## 7. 删除学习与搜题底栏

检索稳定标签和类路径：

```powershell
rg -n 'aaa/learn|AssistantFragment|const-string.*"learn"|const-string.*"assistant"' $WakeupDecoded -g 'ScheduleActivity.smali'
rg -n '学习|表助手|搜题' $WakeupJadx
```

6.2.05 的入口位于：

```text
smali_classes6/com/suda/yzune/wakeupschedule/schedule/ScheduleActivity.smali
```

需删除两段底栏构造逻辑：

1. 条件创建 `aaa/learn/AssistantFragment`，标签为 `assistant`。
2. 创建 `aaa/learn/Oooo000`，标签为 `learn`。

每段应整体移除：

- Fragment `new-instance` 和构造调用。
- tab model 构造。
- `ArrayList.add(...)`。
- 只属于该 tab 的埋点调用。

删除后检查所有 `:cond_*` 和 `:goto_*` 仍有定义。不要只删 `ArrayList.add` 而保留 Fragment 初始化，否则仍可能触发学习模块联网和初始化。

最终验收要求 `ScheduleActivity` 中以下引用均为零：

```text
AssistantFragment
aaa/learn
"learn"
"assistant"
```

## 8. 关闭应用账户与会员

### 8.1 账户状态工具

稳定检索词：

```powershell
rg -n 'ACCOUNT_DXUSS|ACCOUNT_USER_INFO|Saas_submit_logout|USER_GRADE_ID' $WakeupJadx
```

6.2.05 参考类：

```text
com.suda.yzune.wakeupschedule.aaa.utils.o00O0000
```

参考处理：

| 方法 | 语义 | 目标返回 |
| --- | --- | --- |
| `OooO0OO()` | 读取账户令牌 | 空字符串 |
| `OooO0oO()` | 读取 `UserInfo` | `null` |
| `OooOO0()` | 是否已登录 | `false` |

Smali 模板：

```smali
const-string v0, ""
return-object v0
```

```smali
const/4 v0, 0x0
return-object v0
```

### 8.2 自动登录和资料刷新

6.2.05 参考类：

```text
com.suda.yzune.wakeupschedule.aaa.utils.o000OOo0
```

将自动拉取用户资料、自动补全学校/年级等联网入口处理为立即返回。新版通过 `Userupdate`、`Info`、`UserInfo`、`gradeId`、`schoolId` 和网络回调定位。

### 8.3 Hybrid Action

6.2.05 参考类：

```text
aaa/actions/OooO0o.smali              # logout
aaa/actions/OooOOOO.smali             # cancelAccount
aaa/actions/SetGradeInfoAction.smali
aaa/actions/ShowLoginAction.smali
aaa/actions/UpdateUserInfoAction.smali
```

对应 `onPluginAction` 或实际 Action 入口立即 `return-void`。新版应从 `WakeupPlugin` 的方法注册和 Action 调用链反查，不依赖上述混淆文件名。

### 8.4 Manifest Activity

以下 Activity 设为 `android:enabled="false"`，并在存在导出属性时设置 `android:exported="false"`：

```text
com.suda.yzune.wakeupschedule.aaa.activity.login.SYLoginActivity
com.suda.yzune.wakeupschedule.aaa.activity.login.LoginActivity
com.suda.yzune.wakeupschedule.aaa.activity.login.VerificationCodeLoginActivity
com.suda.yzune.wakeupschedule.mine.VipExclusiveActivity
```

## 9. 关闭课表与日历云同步

优先通过 Kotlin 协程类名和网络模型定位：

```powershell
rg -n 'preOptimizeLogin|syncSingleSchedule|synchronizeSchedule|getScheduleFromServer' $WakeupJadx
rg -n 'selectScheduleOnServer|synchronizedCalendars|synScheduleStyle|synScheduleWhenImportSuccess' $WakeupJadx
rg -n 'GetScheduleListBean|SyncScheduleBean|CalendarSynchronize' $WakeupJadx
```

### 9.1 ScheduleActivity 参考映射

6.2.05 文件：

```text
smali_classes6/com/suda/yzune/wakeupschedule/schedule/ScheduleActivity.smali
```

| 混淆方法 | JADX 识别语义 | 处理 |
| --- | --- | --- |
| `o00000()` | 启动时账户检查/同步调度 | `return-void` |
| `o00000oO()` | `preOptimizeLogin` | `return-void` |
| `o0000O0O(I)` | `syncSingleScheduleAsync` | `return-void` |
| `o000OO()` | `synchronizeSchedule` | `return-void` |
| `o0O0O00()` | `getScheduleFromServer` | `return-void` |

### 9.2 ScheduleViewModel 参考映射

6.2.05 文件：

```text
smali_classes6/com/suda/yzune/wakeupschedule/schedule/ScheduleViewModel.smali
```

| 混淆方法 | JADX 识别语义 | 处理 |
| --- | --- | --- |
| `OoooOo0(TableConfig, Continuation)` | `selectScheduleOnServer` | 返回 Kotlin `Unit` |
| `o00O0O(ZZ)` | `synchronizedCalendars` | `return-void` |
| `o0OoOo0(I)` | `synScheduleStyle` | 关闭协程启动 |
| `ooOO(I)` | `synScheduleWhenImportSuccess` | 关闭协程启动 |

协程/Job 返回值需要特别谨慎：

- suspend 函数的正常空操作结果通常返回 `kotlin.Unit`，不要返回任意对象。
- 返回 `Job` 的方法，优先保留方法形状并让协程体空操作，或返回已完成 Job。
- 只有确认所有调用者完全忽略返回值时，才考虑返回 `null`。
- 每次更新都要检索全部调用点，不能沿用旧版假设。

### 9.3 保持高校导入成功

高校导入完成后可能仍调用“导入成功后云同步”。应只短路这个后置同步调用，不应中断：

- 教务页面登录。
- HTML/JSON/CSV 解析。
- 本地数据库写入。
- 切换到新导入课表。
- 导入成功提示。

通过 JADX 和 Smali 检查 `ImportFromEasRouter` 调用云同步后的返回路径，确保返回值未被解引用。

## 10. “我的”页布局清理

6.2.05 参考布局：

```text
res/layout/fragment_mine_tab_content_view_new.xml
```

隐藏以下区域：

```text
mine_user_login_view
ll_mine_vip_card
bannerLayout
ll_mine_tab_content_view_my_collection
ll_mine_tab_content_view_vip
ll_mine_tab_content_view_course
ll_mine_tab_content_view_kf
```

对应控件使用：

```xml
android:visibility="gone"
```

同时关闭：

- `MineNewUserLoginView.updateData()` 的账户数据加载。
- `MineViewModel` 的 `loadBanner` 事件入口。

原登录头部 `layout_mine_user_login_new.xml` 自带 `48dp` 顶部留白。隐藏登录控件后，应将这段间距转移到页面根容器：

```xml
android:paddingTop="48.0dp"
```

并隐藏账户菜单对应的空分隔线，只保留可见菜单之间的分隔线。真机必须检查：

- 状态栏不遮挡首个设置项。
- 刘海、挖孔和不同状态栏高度下不重叠。
- 底部导航不遮挡最后一个设置项。
- 页面滚动、横竖屏和字体放大不出现裁切。

## 11. 构建、对齐与签名

### 11.1 重建

```powershell
$WakeupUnsigned = Join-Path $WakeupOutput 'wakeup-noads-unsigned.apk'
java -jar '.\apk_work\tools\apktool.jar' b $WakeupDecoded -o $WakeupUnsigned
```

构建失败时先处理第一条 Smali 或资源错误，不要继续签名旧产物。

### 11.2 zipalign

```powershell
$WakeupAligned = Join-Path $WakeupOutput 'wakeup-noads-aligned.apk'
& '.\apk_work\tools\android-build-tools\android-14\zipalign.exe' `
  -f -p 4 $WakeupUnsigned $WakeupAligned
```

### 11.3 签名

必须复用精简版历史签名密钥，才能覆盖安装上一版精简包。签名时不要把密码写进脚本、README 或命令历史；省略密码参数，让 apksigner 交互询问。

```powershell
$WakeupSigned = Join-Path $WakeupOutput 'wakeup-noads-signed.apk'
& '.\apk_work\tools\android-build-tools\android-14\apksigner.bat' sign `
  --ks 'PATH_TO_PRIVATE_KEYSTORE' `
  --ks-key-alias 'KEY_ALIAS' `
  --out $WakeupSigned `
  $WakeupAligned
```

签名密钥必须离线备份并从公开仓库排除。密钥丢失后，已安装用户将无法无缝升级到新的精简版签名。

## 12. 最终静态验收

### 12.1 对齐和签名

```powershell
& '.\apk_work\tools\android-build-tools\android-14\zipalign.exe' -c 4 $WakeupSigned
& '.\apk_work\tools\android-build-tools\android-14\apksigner.bat' verify `
  --verbose --print-certs $WakeupSigned
Get-FileHash -Algorithm SHA256 -LiteralPath $WakeupSigned
```

要求：

- zipalign 返回码为 `0`。
- apksigner 输出 `Verifies`。
- 至少 v2/v3 与目标 Android 范围兼容。
- 证书 SHA-256 与上一版精简包一致。

### 12.2 二次反编译最终包

```powershell
java -jar '.\apk_work\tools\apktool.jar' d -f $WakeupSigned -o $WakeupVerify
```

后续所有最终检查都针对 `$WakeupVerify`，不能只检查工作目录。

### 12.3 学习模块检查

```powershell
rg -n 'AssistantFragment|aaa/learn|const-string.*"learn"|const-string.*"assistant"' `
  $WakeupVerify -g 'ScheduleActivity.smali'
```

期望无输出。

### 12.4 Manifest 检查

使用 XML 解析，不用简单字符串替换：

```powershell
[xml]$WakeupManifest = Get-Content `
  -LiteralPath (Join-Path $WakeupVerify 'AndroidManifest.xml') -Raw
$WakeupAndroidNs = 'http://schemas.android.com/apk/res/android'

$WakeupHasInternet = [bool](
  $WakeupManifest.manifest.'uses-permission' |
    Where-Object { $_.GetAttribute('name', $WakeupAndroidNs) -eq 'android.permission.INTERNET' }
)
$WakeupHasInternet
```

另逐项确认：

- 账户、会员、热启动广告 Activity 为 `enabled=false`。
- `SchoolListActivity` 和 `LoginWebActivity` 未被禁用。
- 包名未意外改变。
- 新增广告厂商组件已被识别和处置。

### 12.5 高校导入目录零差异检查

如果本次目标仍是“不修改导入实现”，使用原始对照目录执行：

```powershell
git diff --no-index --quiet -- `
  (Join-Path $WakeupOriginal 'smali_classes6\com\suda\yzune\wakeupschedule\schedule_import') `
  (Join-Path $WakeupVerify 'smali_classes6\com\suda\yzune\wakeupschedule\schedule_import')
$LASTEXITCODE
```

对 `schedule_parser` 重复执行。返回 `0` 表示文本一致。

新版可能调整 DEX 分包，应先用 `rg --files` 找到实际目录，不要假定始终位于 `smali_classes6`。

### 12.6 补丁范围审计

将 `$WakeupOriginal` 与 `$WakeupVerify` 对照，重点确认应用自身代码的变化仅在预期文件。apktool/aapt2 可能重排 `attrs.xml` 枚举顺序或 DEX 内部细节，应判断语义差异，不能只看文件数量。

## 13. 真机回归矩阵

静态检查通过后，至少测试：

### 启动与广告

- 冷启动无开屏广告、黑屏或空白广告页。
- 从后台恢复无热启动广告页。
- 课表浏览无插屏和信息流广告。
- 连续启动、切换前后台多次无崩溃。

### 本地功能

- 新建、编辑、删除本地课程。
- 多课表切换。
- 时间表、颜色、周数和显示设置。
- 本地导入与导出。
- 小组件或提醒功能（如计划保留）。

### 高校导入

- 打开学校列表。
- 搜索并选择高校。
- 教务 WebView 正常联网。
- 登录、验证码和学期选择正常。
- 成功解析并写入本地课表。
- 导入后不触发应用云同步或账户登录。
- 断网和登录失败时错误提示合理，不出现应用账户网络错误。

### “我的”页

- 无登录、会员、收藏和已购课程入口。
- 首项不被状态栏、刘海或挖孔覆盖。
- “课表设置”“全局设置”“常见问题”“更多”可正常打开。
- 大字体和显示缩放下无重叠或裁切。

### 升级

- 使用上一版精简包安装后，当前版可直接覆盖升级。
- 本地课表数据升级后仍存在。
- 官方版因证书不同而无法直接覆盖属于预期行为。

ADB 参考：

```powershell
& '.\apk_work\tools\platform-tools-dist\platform-tools\adb.exe' devices -l
& '.\apk_work\tools\platform-tools-dist\platform-tools\adb.exe' install -r $WakeupSigned
```

只有在确认目标设备和备份状态后再执行安装。

## 14. 常见失败与处理

### apktool 报 Smali 标签不存在

原因通常是删除代码块后仍有分支跳向被删的 `:cond_*` 或 `:goto_*`。检查整个方法的所有标签定义与引用。

### VerifyError 或启动即崩溃

常见原因：

- 返回类型错误。
- `.locals` 不足。
- `move-result` 与前一条 invoke 不再相邻。
- 删除类后仍存在混淆引用。
- suspend 方法错误返回 `null` 或错误对象。

优先回退单个补丁，从最小业务入口短路重新实现。

### 高校导入打不开

依次确认：

1. `INTERNET` 权限仍存在。
2. `SchoolListActivity`、`LoginWebActivity` 未禁用。
3. WebView/文件 Provider 没被广告组件正则误伤。
4. `schedule_import`、`schedule_parser` 与新版原始目录一致。
5. 新版教务页面本身是否改版。

### “我的”页被状态栏覆盖

确认隐藏的登录头部是否曾承担顶部 padding/inset。不要仅隐藏控件而忽略其布局占位；将安全间距转移到仍存在的根容器，并在真机检查不同状态栏高度。

### 签名冲突

检查最终证书摘要是否与上一版精简包一致。包名相同但证书不同，Android 会拒绝覆盖安装。

## 15. 回滚策略

每个阶段单独保存补丁或提交：

1. `baseline/new-version`
2. `ads/business-gates`
3. `ads/manifest-components`
4. `remove/learn`
5. `remove/account`
6. `remove/cloud-sync`
7. `ui/mine-cleanup`
8. `release/verification`

某一步出现崩溃时只回退该阶段，不要用旧版整个 Smali 目录覆盖新版。

## 16. 发布清单

- [ ] 输入 APK 来源、版本和 SHA-256 已记录。
- [ ] 原始对照目录未被修改。
- [ ] 广告业务判断全部返回关闭值。
- [ ] 广告配置刷新已停止。
- [ ] 广告 Manifest 组件逐项复核。
- [ ] 广告权限删除经过新版调用点确认。
- [ ] 学习、助手底栏引用为零。
- [ ] 账户 Activity 和 Action 已禁用。
- [ ] 课表、日历云同步入口已禁用。
- [ ] `INTERNET` 权限保留。
- [ ] 高校导入、解析目录通过对照检查。
- [ ] “我的”页安全间距与分隔线正常。
- [ ] apktool 重建成功。
- [ ] zipalign 检查成功。
- [ ] apksigner 验证成功且证书连续。
- [ ] 最终 APK 二次反编译检查成功。
- [ ] 真机启动、本地课表和高校导入通过。
- [ ] 最终 APK SHA-256 已更新到 README/Release。
- [ ] 私钥、密码、Token 和本地数据未进入仓库。

## 17. 当前基线文件映射

6.2.05 已修改的应用文件主要包括：

```text
AndroidManifest.xml
res/layout/fragment_mine_tab_content_view_new.xml
smali_classes5/com/suda/yzune/wakeupschedule/aaa/actions/OooO0o.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/actions/OooOOOO.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/actions/SetGradeInfoAction.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/actions/ShowLoginAction.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/actions/UpdateUserInfoAction.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/resume/ResumeSplashActivity.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/utils/OooOOOO.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/utils/o000OOo0.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/utils/o00O0000.smali
smali_classes5/com/suda/yzune/wakeupschedule/aaa/widget/MineNewUserLoginView.smali
smali_classes6/com/suda/yzune/wakeupschedule/schedule/ScheduleActivity.smali
smali_classes6/com/suda/yzune/wakeupschedule/schedule/ScheduleViewModel.smali
smali_classes6/com/suda/yzune/wakeupschedule/viewmodel/MineViewModel.smali
```

此清单只用于快速定位。下一版若类移动、拆分或重命名，应以关键词、调用链和功能测试为准。

## 18. 工具清理与长期保留

本次临时安装的工具都集中在 `apk_work/tools/`，未写入系统级环境变量或安装目录。完成构建后，可以清理：

```text
apk_work/tools/apktool.jar
apk_work/tools/jadx/
apk_work/tools/jadx-1.5.6.zip
apk_work/tools/android-build-tools/
apk_work/tools/build-tools_r34-windows.zip
apk_work/tools/platform-tools-dist/
apk_work/tools/platform-tools-latest-windows.zip
apk_work/tools/repository2-1.xml
```

JDK 21 和 ripgrep 是本次任务开始前已有的系统工具，不属于上述临时安装清单。

apktool 还可能使用用户目录下的框架缓存：

```text
C:\Users\<USER>\AppData\Local\apktool\framework\1.apk
```

该缓存可能被其他 apktool 项目共用，删除前先确认用途。

以下内容不是临时工具，后续升级仍需要，必须单独备份：

```text
apk_work/keys/wakeup-noads-local.jks
上一版最终签名 APK
签名证书 SHA-256 记录
每个版本的补丁报告和验收结果
```

尤其不要把整个 `apk_work/` 当作工具目录直接清理，否则会同时丢失签名密钥和升级基线。私钥及密码只存放在受保护的离线位置，不进入 Git 历史。
