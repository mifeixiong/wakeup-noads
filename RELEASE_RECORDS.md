# WakeUp 精简版本记录

本文档是仓库中唯一集中记录具体上游版本和构建结果的版本索引，用于说明每个精简版的输入、变更范围和验收状态。README 与维护手册只保留跨版本规则，不应复制本文件中的版本号、类名、哈希或统计数字。逐条命令、二次解包结果、差异文件和回滚输出保存在对应版本的 `work/<version>/reports/` 目录；发布时应将需要公开的报告和最终 APK 作为 Release 附件保存。`work/` 目录默认被 `.gitignore` 排除，不应把其中的密钥、原始 APK、账号数据或完整反编译目录提交到仓库。

## 6.3.0 版本链

| 构建 | 基线 | 主要变更 | APK SHA-256 | 状态 |
| --- | --- | --- | --- | --- |
| `6.3.0-r1` | 官方 `6.3.0` / `versionCode 510` | 去广告、学习/助手、账户/会员、云同步和“我的”页精简 | `8F7E9A8DCEDD6644FD24FEF658B682A3F8D4769EA72441596173E17C4CBEE4CF` | 已完成静态验收 |
| `6.3.0-r2` | `6.3.0-r1` | 移除“我的”页电脑端扫码 / PC 插件登录 | `0A4588E5011F70BDFFDF9D27F00856109E8720F345FA04B4C669E2B35FAB2AD7` | 已完成静态验收 |
| `6.3.0-r3` | `6.3.0-r2` | 移除普通更新提醒、自动更新检查、`forceUp` 强制更新和“关于”页版本弹窗 | `C5B6489D10639F2DBBA80FB641475607E62CCCE04624EA6B51CF2EE0584EE194` | 当前参考构建 |
| `6.3.0-r4` | `6.3.0-r3` | 针对 [Issue #2](https://github.com/Lorikein12138/wakeup-noads/issues/2)，关闭导入时上传整页 HTML 的 `schedule_analysis` 网络上报，保留本地正方课表解析和写库 | `98E72CAD74C0F332DA0B642A4E42AEF47EADD659D519ABE13968F10AA68FDA29` | 构建、静态验收和 Release 已完成；真机回归待测 |

共同信息：包名为 `com.suda.yzune.wakeupschedule`，最低 Android 为 API 24，精简版签名证书 SHA-256 为 `C723A71F393C421EE02496408601F195DA96DC1D5FD6D7432FDF46F33699F79A`。官方输入 APK SHA-256 为 `60CD13CE634F8CE53B510E9CEDAE2C3EE741A10229D63C7E83AC95C7E46D808D`。

## 当前验收

`6.3.0-r3` 的最终二次解包验证结果：

- 147 个已识别广告组件全部为 `android:enabled="false"`。
- 学习/助手引用为 0，`android.permission.INTERNET` 保留。
- `schedule_import` 和 `schedule_parser` 与官方 6.3.0 对照目录零差异。
- 主页更新检查、官方更新请求、普通/强制更新弹窗和“关于”页版本检查均已短路。
- `6.3.0-r4` 的 `schedule_analysis` 上报入口已短路；二次解包后 `schedule_import`（479 个文件）和 `schedule_parser`（399 个文件）与 r3 零差异。
- r4 APK 已通过 apktool 重建、zipalign、APK v2/v3 签名和二次解包；Issue #2 的设备实测仍待完成。
- apktool 重建、zipalign、APK v2/v3 签名和最终二次解包通过。
- 回滚副本已恢复为 r2 哈希 `0A4588E5011F70BDFFDF9D27F00856109E8720F345FA04B4C669E2B35FAB2AD7`。
- ADB 连接设备数为 0，真机启动、本地课表和高校导入回归仍需在连接设备后完成。

r3 实际工具版本：apktool `3.0.3`、JDK `21.0.10`、Android Build Tools `36.0.0`（`apksigner 0.9`）、ADB `37.0.0-14910828`。报告同时记录了实际工具路径和命令退出状态。

详细证据：`work/6.3.0/reports/`（r1 基线）以及其中的 `r2/`、`r3/`、`r4/` 子目录。其中每个版本目录的 `VERIFICATION.txt` 记录基线、修改版和回滚命令的字面输出及退出状态，`wakeup-noads-*.diff` 记录相邻构建的文件差异，`ROLLBACK.sh` 用于验证上一版精简包可恢复；r4 的公开 Release Notes 也保存在 `work/6.3.0/reports/release-notes-v6.3.0-r4.md`。

## 后续官方版本

官方发布新版本后，必须新建独立的 `work/<new-version>/` 目录并重新执行 [UPDATE_WORKFLOW.md](./UPDATE_WORKFLOW.md)：

1. 固化官方 APK 原件、来源、版本号、`versionCode`、SHA-256、原始证书和未修改对照目录。
2. 重新审查广告、学习/助手、账户/会员、云同步、电脑端扫码以及 APK 更新提醒和强制更新链路。
3. 以本记录中的业务目标作为检查清单，但只迁移经过新版调用链、返回值和真机行为确认的补丁。
4. 为每个阶段保留 `MODIFIED_FILE`、`DIFF_FILE`、`VERIFICATION.txt` 和可执行 `ROLLBACK.sh`，并测试独立副本回滚。
5. 重新构建、签名、二次解包、静态验收和真机回归，再新增一行版本记录和对应 Release 说明。

不能仅凭旧版类名、方法行号、资源 ID 或 Smali 寄存器位置判断新版实现；新版可能新增、拆分、重命名或移除模块。课表导入和解析目录应继续作为不可修改边界逐版对照。
