# WakeUp 精简版本记录

本文档是仓库中唯一集中记录具体上游版本和构建结果的版本索引，用于说明每个精简版的输入、变更范围和验收状态。README 与维护手册只保留跨版本规则，不应复制本文件中的版本号、类名、哈希或统计数字。逐条命令、二次解包结果、差异文件和回滚输出保存在对应版本的 `work/<version>/reports/` 目录；发布时应将需要公开的报告和最终 APK 作为 Release 附件保存。`work/` 目录默认被 `.gitignore` 排除，不应把其中的密钥、原始 APK、账号数据或完整反编译目录提交到仓库。

构建产物以 SHA-256 作为唯一身份；同一上游版本产生不同摘要时，必须使用不同的构建标识并分别记录，不能覆盖或混用报告。验收状态采用以下口径：`静态验收通过` 表示解包、调用链和边界检查完成；`构建验收通过` 表示重建、对齐、签名和二次解包完成；`真机回归通过` 表示目标设备上的实际场景完成；未完成的项目统一标为 `待验证`，不得写成已通过。

## 6.3.0 版本链

| 构建标识 | 基线 | 主要变更 | APK SHA-256 | 状态 |
| --- | --- | --- | --- | --- |
| `6.3.0-r1` | 官方 `6.3.0` / `versionCode 510` | 去广告、学习/助手、账户/会员、云同步和“我的”页精简 | `8F7E9A8DCEDD6644FD24FEF658B682A3F8D4769EA72441596173E17C4CBEE4CF` | 已完成静态验收 |
| `6.3.0-r2` | `6.3.0-r1` | 移除“我的”页电脑端扫码 / PC 插件登录 | `0A4588E5011F70BDFFDF9D27F00856109E8720F345FA04B4C669E2B35FAB2AD7` | 已完成静态验收 |
| `6.3.0-r3` | `6.3.0-r2` | 移除普通更新提醒、自动更新检查、`forceUp` 强制更新和“关于”页版本弹窗 | `C5B6489D10639F2DBBA80FB641475607E62CCCE04624EA6B51CF2EE0584EE194` | 更新阻断基线 |
| `6.3.0-r4` | `6.3.0-r3` | 针对 [Issue #2](https://github.com/Lorikein12138/wakeup-noads/issues/2)，关闭导入时上传整页 HTML 的 `schedule_analysis` 网络上报，保留本地正方课表解析和写库 | `98E72CAD74C0F332DA0B642A4E42AEF47EADD659D519ABE13968F10AA68FDA29` | 最新 Release；静态验收完成，真机回归待测 |

共同信息：包名为 `com.suda.yzune.wakeupschedule`，最低 Android 为 API 24，精简版签名证书 SHA-256 为 `C723A71F393C421EE02496408601F195DA96DC1D5FD6D7432FDF46F33699F79A`。官方输入 APK SHA-256 为 `60CD13CE634F8CE53B510E9CEDAE2C3EE741A10229D63C7E83AC95C7E46D808D`。

## 6.4.0 版本链

| 构建标识 | 基线 | 主要变更 | APK SHA-256 | 状态 |
| --- | --- | --- | --- | --- |
| `6.4.0-r1` | 官方 `6.4.0` / `versionCode 530` | 重新去广告；移除学习/账户/云同步/更新入口；移除导入分享口令、导出在线分享课表、导出菜单分享 App 和个人信息导出；关闭新版任意 URL WebView 入口 | `DBE9710581CFBD517F99ABABA1D3AAFFDEF2405B6BC040A5E53288721A6E7BA5` | 当前 Issue #3 修复基线；静态/构建验收通过，真机回归待验证 |
| `6.4.0-r1-legacy` | 官方 `6.4.0` / `versionCode 530` | 与 `6.4.0-r1` 同一精简范围的历史构建，仅用于保存既有证据，不作为当前修复基线 | `55872D055CCD8AF712B0095869D8667DFEBB68FE88953673186E2F6E40E720D5` | 已归档；禁止与当前 `6.4.0-r1` 混用 |
| `6.4.0-r1-issue3` | 当前精简版 `6.4.0-r1` | 针对 [Issue #3](https://github.com/Lorikein12138/wakeup-noads/issues/3)，恢复教务动态解析请求所需的已保存应用会话只读读取；不恢复账户/云同步/分享入口，且不修改 6.3.0-r4 | `AC7BBF797B8948A712EA3EC78CEF4F5B042F0177002585C19BC0BC54E6731FB7` | apktool/zipalign/v2-v3/二次解包通过；真机导入回归待设备连接 |

6.4.0 输入与签名信息：

- 官方输入 APK：`work/6.4.0/input/base.apk`
- 官方输入 SHA-256：`3E6D56EC0FC4EE9D23F9819D5B1DCF8BCC5B757079DEC47AF532F9B3CBB0744F`
- 官方证书 SHA-256：`547726FCAAE0F52311BD9696C8D1714419EF66B64766A69C5818FC89B767EFED`
- 精简版证书 SHA-256：`C723A71F393C421EE02496408601F195DA96DC1D5FD6D7432FDF46F33699F79A`

6.4.0 的新版审查记录：

- 147 个已识别广告组件全部禁用；10 项广告/设备标识权限和 1 项 Huawei ads-identifier 元数据移除。
- 新增 FastAd 流量广告配置、广告位插入、广告位门控、推广弹窗及热启动广告路径均已短路。
- 导入分享口令、导出在线分享课表、导出菜单分享 App 的 UI 与调用路由均已去除；本地 EAS、文件/Excel/HTML/备份导入和 ICS 导出保留。
- “我的 - 更多 - 个人信息导出”涉及的个人资料读取、导出、系统分享和资料更新 Action 均已短路。
- 新发现的 `wakeup_openWebOverCurrentPage` → `ShareWebActivity` 任意 URL 在线入口已短路并禁用；通用 HTTP/文件下载仅因高校导入需要而保留。
- `schedule_import` 和 `schedule_parser` 与官方 6.4.0 对照目录零差异。

详细证据、变更摘要、Manifest JSON、回滚脚本和 Release Notes：`work/6.4.0/reports/r1/`。

6.4.0-r1 Issue #3 修复记录：

- 本次实际输入为当前本地 `work/6.4.0/output/wakeup-noads-v6.4.0-r1.apk`，SHA-256 为 `DBE9710581CFBD517F99ABABA1D3AAFFDEF2405B6BC040A5E53288721A6E7BA5`；`55872...` 已单独登记为历史构建标识 `6.4.0-r1-legacy`。
- 影响：教务页面可登录并显示课表，但点击导入后动态解析脚本请求失败，用户看到 `com.android.volley.ResponseContentError`。
- 根因分类：兼容性回归；当前 r1 的精简改动误伤了共享网络层读取已保存会话的只读状态。
- 静态证据：失败路径进入 `/wakeup/script/enplugin` 动态解析脚本请求；请求公共参数和 Cookie 链依赖被提前返回的会话读取方法。
- 排除项：`schedule_analysis` 是独立的异步统计上报路径，不是动态解析请求的前置依赖；`6.3.0-r4` 不作为修复输入。
- r1 的 `aaa/utils/o00O0000` 曾将 `ACCOUNT_DXUSS`、`ACCOUNT_USER_INFO` 和会话状态读取提前返回空值；修正版仅恢复这三个官方只读实现，使 `WPUSS`/`ZYBUSS` 公共参数及会话 Cookie 链可正常读取。
- `schedule_import`、`schedule_parser`、动态脚本请求模型、通用网络基类和分享/个人信息导出精简边界保持不变；登录、账户更新和云同步 Action 仍短路。
- `6.3.0-r4` 目录、r4 APK 及其 `schedule_analysis` 补丁均未修改，r4 只作为 Issue #3 的问题样本和对照。
- 验证结论：静态定位和构建验收通过；真实教务导入仍待设备回归，当前不宣称已完成全环境兼容性确认。

详细证据、差异说明、验证记录、回滚脚本和 Release Notes：`work/issue-3/reports/`；修正版 APK：`work/issue-3/output/wakeup-noads-v6.4.0-r1-issue3.apk`。

## 当前验收

历史 6.3.0 验收记录：

- 147 个已识别广告组件全部为 `android:enabled="false"`。
- 学习/助手引用为 0，`android.permission.INTERNET` 保留。
- `schedule_import` 和 `schedule_parser` 与官方 6.3.0 对照目录零差异。
- 主页更新检查、官方更新请求、普通/强制更新弹窗和“关于”页版本检查均已短路。
- `6.3.0-r4` 的 `schedule_analysis` 上报入口已短路；二次解包后 `schedule_import`（479 个文件）和 `schedule_parser`（399 个文件）与 r3 零差异。
- r4 APK 已通过 apktool 重建、zipalign、APK v2/v3 签名和二次解包；Issue #2 的设备实测仍待完成。
- 6.3.0 的 apktool 重建、zipalign、APK v2/v3 签名和最终二次解包通过。
- 回滚副本已恢复为 r2 哈希 `0A4588E5011F70BDFFDF9D27F00856109E8720F345FA04B4C669E2B35FAB2AD7`。
- ADB 连接设备数为 0，真机启动、本地课表和高校导入回归仍需在连接设备后完成。

6.4.0-r1 最终二次解包验收结果：

- 147 个已识别广告组件全部为 `android:enabled="false"`，`android.permission.INTERNET` 保留。
- 新版 FastAd 广告入口、热启动广告、更新/账户/云同步路径及新增任意 URL WebView 入口均已短路或禁用。
- 导入分享口令、导出在线分享课表、导出菜单分享 App 和“我的 - 更多 - 个人信息导出”不可达；本地导入/ICS 导出和高校导入目录保留。
- `schedule_import`、`schedule_parser` 零差异；APK 已通过 apktool、zipalign、v2/v3 签名和二次解包。
- `6.4.0-r1-issue3` 回滚脚本已用独立副本测试通过，并恢复到当前 `6.4.0-r1` 基线；当前环境没有 `adb` 命令，真机回归待设备连接。
- 6.4.0-r1 Issue #3 修正版 `AC7BBF797B8948A712EA3EC78CEF4F5B042F0177002585C19BC0BC54E6731FB7` 已通过 apktool 重建、zipalign、APK v2/v3 签名和最终二次解包；`schedule_import`、`schedule_parser` 及动态解析请求相关文件与官方 6.4.0 零差异。
- Issue #3 修复基线为当前 6.4.0-r1，未修改 6.3.0-r4；修正版回滚副本已恢复到 r1 基线哈希 `DBE9710581CFBD517F99ABABA1D3AAFFDEF2405B6BC040A5E53288721A6E7BA5`。
- 由于当前环境没有 `adb` 和可用教务测试账号，Issue #3 的真实点击导入仍待设备回归；静态根因、修复范围、证据等级和新版广告/在线入口审查已记录。

6.3.0 历史构建的工具版本为：apktool `3.0.3`、JDK `21.0.10`、Android Build Tools `36.0.0`（`apksigner 0.9`）、ADB `37.0.0-14910828`。6.4.0-r1-issue3 的实际命令、退出状态和设备可用性单独记录在 `work/issue-3/reports/VERIFICATION.txt`。

详细证据：`work/6.3.0/reports/`（r1 基线）以及其中的 `r2/`、`r3/`、`r4/` 子目录。其中每个版本目录的 `VERIFICATION.txt` 记录基线、修改版和回滚命令的字面输出及退出状态，`wakeup-noads-*.diff` 记录相邻构建的文件差异，`ROLLBACK.sh` 用于验证上一版精简包可恢复；r4 的公开 Release Notes 也保存在 `work/6.3.0/reports/release-notes-v6.3.0-r4.md`。

## 后续官方版本

官方发布新版本后，必须新建独立的 `work/<new-version>/` 目录并重新执行 [UPDATE_WORKFLOW.md](./UPDATE_WORKFLOW.md)：

1. 固化官方 APK 原件、来源、版本号、`versionCode`、SHA-256、原始证书和未修改对照目录，并为每个产物分配不可复用的构建标识。
2. 重新审查广告、新增广告/在线入口、学习/助手、账户/会员、云同步、电脑端扫码、导入/导出分享、个人信息导出以及 APK 更新提醒和强制更新链路。
3. 以本记录中的业务目标作为检查清单，但只迁移经过新版调用链、返回值和真机行为确认的补丁。
4. 为每个阶段保留 `MODIFIED_FILE`、`DIFF_FILE`、`VERIFICATION.txt` 和可执行 `ROLLBACK.sh`；对兼容性问题另外记录影响、根因分类、证据等级、排除项、非目标和未完成测试，并测试独立副本回滚。
5. 重新构建、签名、二次解包、静态验收和真机回归，再新增一行版本记录和对应 Release 说明。

不能仅凭旧版类名、方法行号、资源 ID 或 Smali 寄存器位置判断新版实现；新版可能新增、拆分、重命名或移除模块。课表导入和解析目录应继续作为不可修改边界逐版对照。
