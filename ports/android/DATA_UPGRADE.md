# Android 历史资源无损迁移

> 本文记录 1.31～1.33 的内置 ZIP / Coordinator 迁移契约。1.34 主启动路径改为 [资源分离与本地导入](RESOURCE_IMPORT.md)：独立选择记录优先、没有选择时才校验旧 active/唯一完成根。普通显式修复可用完整可信来源写全新目录，保留损坏的旧登记和旧目录，不在旧树推断所有权；有 pending 则必须先完整验证来源并精确匹配登记 ZIP，才调用下述 Coordinator 受控恢复。无 pending 但有未归属 journal/snapshot/txn 仍拒绝，不清档也不要求降级回装旧应用。

## 已确认的 1.32 缺陷

实际 1.29、1.30 的旧安装器仅创建资源完成标记，不创建私有 active.manifest；1.31 才接入 DataCoordinator。存档由独立的 getExternalFilesDir(null)/wmmt 提供给 nativeStart，资源目录为其兄弟 re3dxplus-data/<ZIP-SHA>-UUID，不是存档目录。

已发行 1.29 双后端、1.30、1.31 的主体 ZIP SHA256 都是：

`4f5d55802f46c010a2db383e758ee3917f85c029a956278f5b564f856a7a3e59`

1.32 主体改为 `a8870bc3f299292af952f456f0c504d231cd858ae7e1b36db3e9096c3d87f7b6`，因此“没有私有清单时仅采纳当前ZIP完成标记”的旧逻辑会拒绝正常1.29/1.30用户。不能归因于玩家清数据或资源损坏。原同ZIP先采纳、再跨ZIP的测试没有覆盖此真实路径。

## 修复契约

1. 固定APK资产 data-baselines.zip 携带由已审历史资源生成的完整 DMF1 清单；绝不从玩家磁盘学习或自签一份旧基线。ZIP/DMF内部校验只能发现损坏，认证权来自签名APK和独立审定的生成输入。
2. 先处理已有 active/pending。损坏的active不是“没有active”；缺失/损坏恢复状态不允许绕过。历史catalog按需加载，不影响已有登记状态的正常更新/恢复。
3. 只枚举安全、带严格完成标记、且由当前ZIP或受审catalog支持的目录，先计数后验证；两个可识别候选即拒绝，不能用mtime、目录顺序或“过滤掉坏的那个”猜选。
4. 唯一候选中完整验证每个旧资源的无symlink路径、regular文件、长度、SHA256，再以原canonical ID和原UUID目录持久化旧active并同步。只有这之后才复用现有journal/overlay更新逻辑。
5. 清单仅授予列明文件的权限，不授予整个目录。未知根内文件、未支持旧SHA/markerless/in-progress兄弟目录保持原样、不被认领；它们不使唯一受审完成根失去资格。没有可识别候选而base非空仍拒绝，不能伪装全新安装。private orphan journal/manifest/txn等是事务状态，不是可忽略兄弟目录。
6. in-progress根自身不可采纳。失状态的混合old/new内容不能当完整旧基线；受审资源缺失、改动或变symlink均拒绝，不清档、不强覆写。版本升级后目录名仍保留初次安装SHA，因此查catalog用完成标记中的SHA，而不是强令目录名前缀等于最新SHA。

## 构建不得遗漏清单

使用 tools/build_data_baselines.py，从每个**独立审过的ZIP及其已确认SHA**生成小清单catalog，不能拿任意ZIP现场观察到的SHA冒充审定来源。所有派生文件输出到新的外置工作目录，不把原素材或生成清单提交到公开源码。

```sh
JAVA_HOME=/path/to/jdk python3 tools/build_data_baselines.py \
  --baseline REVIEWED_OLD_SHA256=/path/to/reviewed-old.zip \
  --baseline REVIEWED_CURRENT_SHA256=/path/to/reviewed-current.zip \
  --output-dir /Volumes/CodexWork/new-exclusive-catalog

# In an explicitly approved snapshot build:
export GAME_DATA_BASELINES_ZIP=/Volumes/CodexWork/new-exclusive-catalog/data-baselines.zip
```

凡设置GAME_DATA_ZIP的构建，必须同时设置GAME_DATA_BASELINES_ZIP。脚本编入DataBaselines，并用host-only DataBaselineCompiler验证catalog后打入APK；不能只改Java却漏资产。外置受控构建助手还要求 --expected-baselines-sha256，并回读包内资产SHA。其脚本review pins仍保留人工源码复核门槛，不因本修复自动解除。

每次主体ZIP变化，保留受支持升级窗口的历史catalog，至少覆盖仍在使用的1.29/1.30，以及上一主体版本。清单很小，不需在APK内再携带一份完整旧资源ZIP。

## 回归与证据边界

```sh
JAVA_HOME=/path/to/jdk PYTHONDONTWRITEBYTECODE=1 \
  python3 -B tests/test_data_upgrade_host.py -v
```

统一runner在新的外置目录编译并运行：原manifest/overlay/coordinator、catalog严格解析、旧目录引导故障恢复，以及**从当前MainActivity提取的真实prepareData方法**的AssetManager host替身接线（含catalog丢失/坏数据、已有active/pending优先与存档哨兵）。构建接线测试确认显式Java列表和打包资产，不是APK或真机测试。

真实1.29安装方法+真实1798资源到1.32主体的另行外置回归已验证：没有人为预写active，自动发布旧基线后全1798新版SHA通过；仅5个Subaru WPK和完成标记变化，存档/未知文件/未知兄弟及UUID目录不变。不能把synthetic595项检查或包内CRC单独称作这条真实升级链证据。

这是源码与host/真实资产副本验证，不是真机Android文件系统或断电验证；此源码修改本身不会修复玩家已经下载的1.32 APK，需要经授权重新构建、签名及回读新包。不要要求玩家卸载/清数据；更高versionCode的修复包才可覆盖已经安装的1.32，不建议降级绕过。
