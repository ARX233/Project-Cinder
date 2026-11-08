# Android 1.34 离线资源导入工具（host 草案）

## 范围、版权与不可做的事

- **版权：仅供玩家有权使用的自有旧直装 APK，在本地电脑离线提取自用运行资源。** 源 APK、提取结果及私有收据均不要公开再分发；工具不提供 APK/游戏素材下载链接，不赋予任何素材使用权。
- **这不是原版转换器。** 原版街机目录 IGB → WPK 的完整转换尚未完成。不能把原版目录、`main`/ELF 或启动器交给此工具并声称转换成功；本工具不启动、执行、安装或导入原版程序。
- 不访问设备，不运行 APK 代码/launcher，不导入玩家 save；不修改旧 APK、既有文件、存档或任何游戏安装目录。
- Android 1.34 无资源 APK 的构建输入只有已有小型 DMF1 catalog 和纯文本 sidecar index，**不把运行资源 ZIP 或本页测试 fixture 打入 APK/repo**。
- 公共 CLI 接受玩家**显式指定的宿主系统绝对输出路径**，不限某台开发机的卷名；其父目录必须已存在，整条父目录链不得有 symlink/junction/reparse point。工具不自动选择 cwd、home 或系统临时目录，也不自动创建父目录。需要 Python 3.9+ 标准库；无 pip、Java、Android SDK、联网或第三方 ZIP 命令依赖。
- 本项目本次所有实跑、合成 fixture、日志、私有集成资源仍严格只新建在 `/Volumes/CodexWork`。目前证据是 macOS host 实跑及纯 Windows 路径/目录属性模拟测试，**不是 Windows/Linux 实机验证或所有文件系统兼容性承诺**。请选自己有权写入的私有本地目录；若需要完全离线，先确认源和目标不依赖云盘下载或网络共享。

## 信任边界

两个工具都**不会通过“给当前看到的玩家文件计算哈希”而创造信任**。

1. 构建者先独立审定一个完整源 APK 的 SHA-256，再将该 pin 显式传给 [metadata 生成器](../tools/build_resource_metadata.py)。生成器先验证完整 APK，再读取其真实 assets；可额外对照审定的资源输入 JSON 和既有 CardResources spec。它不扫描玩家目录，也不生成 Java 接口。
2. [离线打包器](../tools/resource_import_pack.py) 必须显式传入构建者已审的 DMF1 `--catalog` 和 `--sidecars-index`。散落在玩家目录的同名文件、APK 内自带的 catalog 或任意 observed hash，都不是自动信任来源。收据记录这两个输入的 SHA，但**收据和 DMF1 body checksum 不是签名/真实性证明**；分发者应通过自己的可信渠道核对 metadata/catalog 摘要。
3. APK signing block 仅做结构检查；工具不验证 APK 签名证书。生成器的显式完整 APK SHA 审定，以及打包器的外部已审 entry map，是不同的信任边界。

当前唯一允许的 main baseline 身份：

```text
old:     4f5d55802f46c010a2db383e758ee3917f85c029a956278f5b564f856a7a3e59
current: a8870bc3f299292af952f456f0c504d231cd858ae7e1b36db3e9096c3d87f7b6
```

源 main ZIP 的容器 SHA 可以因压缩参数、mtime、注释等变化而不同，但**全部 1798 个文件的 path/bytes/SHA-256 entry map 必须逐条等于这两份已审 catalog 之一**。已知容器 hash 本身不会跳过内容校验；unknown entry/hash 不会退化为“试试看”。

## 构建者：生成纯文本 metadata

从 `ports/android` 运行，显式替换已审 APK、pin 与新输出目录；以下外置路径只是本机审计示例，不是公共 CLI 的卷名限制。不要把未经审定文件的现算 hash 填入参数并称为审核：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/build_resource_metadata.py \
  --from-apk /Volumes/CodexWork/reviewed/source.apk \
  --approved-apk-sha256 INDEPENDENTLY_REVIEWED_64_LOWER_HEX_SHA256 \
  --resource-inputs /Volumes/CodexWork/reviewed/android-resource-inputs.json \
  --card-spec android/java/com/wmmt/port/CardResources.java \
  --output-dir /Volumes/CodexWork/new-metadata-output
```

`--resource-inputs`、`--card-spec` 是额外的只读审定 pin/spec 一致性检查，可省略；完整 APK 的 `--approved-apk-sha256` 不可省略。生成目录必须不存在。输出仅有纯文本 `sidecars-index-v1.tsv` 和私有 `receipt.json`，**不含 payload**；card ZIP 仅在有界内存中读取。收据记录完整 APK、7 个资源 asset（含 main ZIP、catalog 和 card ZIP）、41 个单资源及 metadata 的 bytes/SHA-256。

### Sidecar index v1

```text
WMMT-SIDECARS-1\n
sorted/path<TAB>bytes<TAB>64lowerhexSHA256\n
```

这是 UTF-8 无 BOM、LF 结尾的纯文本（上例 `\n`/`<TAB>` 表示真实换行/制表符）。最多 64 KiB、512 行资源项；当前完整集合固定为 **41 文件**：

- 根路径 top4：`story-cutin.bin`、`card-pages.bin`、`backfire.wpk`、`backfire.bfx`。
- `card-resources/manifest.json`、`card-resources/meters-v2.bin`。
- `card-resources/bgm-extra/wm2_01.m4a` 至 `wm2_23.m4a`，以及 `wmr_01.m4a` 至 `wmr_12.m4a`。

card 子集合 37 项**包含 manifest**；iOS 的 40 payload 计数不包含 card manifest，二者口径不要混用。当前 host 工具不接受未知 BGM 名或不完整集合。

## 玩家：生成纯运行资源 ZIP

只使用有权使用的自有旧 APK 和可信构建者给出的 metadata/catalog：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/resource_import_pack.py \
  --from-apk /Volumes/CodexWork/private/my-owned-old.apk \
  --catalog /Volumes/CodexWork/trusted/data-baselines.zip \
  --sidecars-index /Volumes/CodexWork/trusted/sidecars-index-v1.tsv \
  --output /Volumes/CodexWork/private/new-runtime-resources.zip
```

玩家可以把上述参数替换为自己本地的绝对路径。Windows 参数形状示例（只示范路径，不代表已在 Windows 实机运行）：

```powershell
python -B tools/resource_import_pack.py --from-apk "C:\Users\Player\Owned\old.apk" --catalog "C:\Users\Player\Trusted\data-baselines.zip" --sidecars-index "C:\Users\Player\Trusted\sidecars-index-v1.tsv" --output "C:\Users\Player\Private\new-runtime.zip"
```

Linux 参数形状示例（同样不是 Linux 实机验证）：

```sh
python3 -B tools/resource_import_pack.py --from-apk /home/player/owned/old.apk --catalog /home/player/trusted/data-baselines.zip --sidecars-index /home/player/trusted/sidecars-index-v1.tsv --output /home/player/private/new-runtime.zip
```

父目录 `Private`/`private` 须事先由用户创建，目标 ZIP 及其自动派生 receipt 均须不存在。Windows 不接受 `C:relative.zip`、根相对路径、ADS（`name:stream`）、DOS 保留设备名、尾部空格/点或设备/extended namespace；普通完整 drive 路径和显式 UNC 绝对路径可做校验，但工具本身不建立网络连接。成功退出码为 0，打印输出 SHA 与私有收据位置。输出 ZIP 是 **1839 个文件**：

```text
<1798 main resources at ZIP root; NO data/ prefix>
story-cutin.bin
card-pages.bin
backfire.wpk
backfire.bfx
card-resources/manifest.json
card-resources/meters-v2.bin
card-resources/bgm-extra/<35 approved .m4a files>
```

输出不会含 `classes.dex`、`lib/`、`AndroidManifest.xml`、签名/META-INF、main/launcher、存档、catalog、metadata 或 receipt。APK 的无关代码/签名条目只做 ZIP 结构检查，不解压执行或复制；被选资源条目逐一做 CRC、长度、SHA 检查。仅从 APK 的 `assets/re3dxplus-data.zip`、top4 assets、`assets/card-resources-v1.zip` 取素材，不扫描其他路径。

## 安全与失败语义

- 中央目录/本地头/descriptor/大小/CRC 绑定检查；拒绝多卷、ZIP64、加密、不支持压缩、symlink/特殊文件、重叠、隐藏 local 条目、截断、额外尾随字节与不明 gap。outer APK 仅允许完整的 APK Signing Block、紧邻其前且对齐到 4096 边界的至多 4095 字节全零 padding，以及 zipalign 的有界 local-extra 全零 TLV/填充；nested ZIP/catalog 没有这些例外。
- 路径拒绝绝对路径、反斜杠、冒号、控制字符、非 NFC、`..`、空组件、保留目录；检查 duplicate、Unicode NFC/casefold 碰撞、隐式父目录 alias、file/directory 冲突。不使用 `extractall`，不会把输入条目名当作文件系统写入路径。
- main 扩展总量 ≤ 3 GiB、单文件 ≤ 512 MiB；card ≤ 110,000,000 bytes；sidecars 总量 ≤ 256 MiB；APK/输出 ZIP ≤ 2 GiB；catalog ≤ 16 MiB、每 DMF1 ≤ 2 MiB。路径数、结构缓冲、metadata、解压读块均有界；CRC/SHA 流式计算。超限明确失败而非放宽校验。
- 所有源文件只读打开，源文件本身拒绝 symlink/Windows reparse point；完整 APK 前后重新哈希，文件 lstat/open 身份和描述符 stat 前后核对。输出另须通过整条父目录链的 non-link directory 检查。应使用不再被其他程序修改的本地源文件；这不是对抗同权限恶意并发替换目录的 OS sandbox，也不承诺各平台 ACL/权限行为一致。
- `--output` 和自动派生的 `<output>.receipt.json` 必须都不存在（文件、目录、有效或 dangling symlink 都不能占位）。最终文件用 **CREATE_NEW / `xb` 独占流式复制**发布并重算 SHA、fsync，不要求文件系统支持 hard link，绝不覆盖、rename 或删除用户路径。独占创建不等于整个写入过程原子；I/O 失败可能留下仅本次新建的部分 ZIP/receipt，这些对象保留供检查而不自动删除。
- 每次打包只在**显式 output 的同一父目录**下创建唯一 `.work-<UUID>` 目录，按宿主文件权限/ACL 尝试私有化。目录包含仅本次写出的两个 nested 资源 ZIP、已验证结果、收据或 failure 记录；成功/失败均保留以便审计。不使用系统 `/tmp`/`TEMP`，不扫描、清理或上传其它目录。请自己确认后清理自己的目录；工具不自动删除任何数据。
- ZIP 与 receipt 是两个独占写入操作，**不是原子双文件事务**；中断可能只留下一个完整文件或新的部分文件。只有零退出确认两者已完整校验并发布；失败重试必须选新的输出路径，工具不会删除遗留文件。
- 可复现规则：路径排序、mtime 固定 `1980-01-01`、Unix regular `0644`、无额外注释、DEFLATE level 6。同 Python/zlib 版本及相同 entry map 得到相同 bytes；跨 zlib 版本的压缩字节一致性不作承诺。收据记录 Python/zlib 版本及全部输出成员摘要。压缩以避免当前真实 2.28 GB main 数据形成超 Android 上限的 STORED ZIP。

## Host 合成测试

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/test_resource_import_pack.py
```

[测试源码](../tools/test_resource_import_pack.py) 只合成 1798 个很小的 main 条目和 41 个假 sidecar，不需要原素材。测试覆盖错误 pin、错 hash、坏 DMF、duplicate/unsafe/casefold/NFC/symlink、CRC/central/descriptor/gap/预算异常、既存 output/receipt 保留、纯资源输出、重复打包可复现、CLI 版权说明；另以纯 `PureWindowsPath` 和模拟目录属性检查 drive/UNC、相对路径、ADS/DOS 名、symlink/junction/reparse 拒绝，以本机外置路径验证父链、不覆盖、无 hard-link/rename/delete 的独占发布及工作目录位置。Windows 模拟不会创建任何 Windows 路径，也不等价于 Windows 实机测试。所有实际 fixture 和日志仍只留在 `/Volumes/CodexWork`，不写 repo 的 asset/build/安装/设备目录。

真实审定 1.33 APK 的 metadata 与私有纯资源包另存外置集成 fixture，不公开 present，也不纳入源码或自动测试分发。此草案不宣称 Android SAF/UI/运行效果验证完成；那些由父端集成验证。
