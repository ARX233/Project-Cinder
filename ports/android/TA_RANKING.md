# 待机 TA 榜与未来全服接口

## 已接入的范围

这是**本机、未经过服务器核验的 TA 整条赛道完赛榜**，不是任意单圈计时，也不是已上线的全球榜。真实普通 TA 完赛才进入新榜；旧 PB、车型包最佳和称号流程保留，不能把它们当作有完整来源的新榜成绩导入。

- [原生成绩观察接口](<src/car.h>)、[只读实现](<src/car.c>)：读取实际 Native 模式、比赛场地、有效车辆配置、原生 float32 elapsed 与已通过检查点，不推进物理、不修改时钟/RNG。
- [APP 入口与生命周期](<src/app_ta_rank.inc>)：成功开赛后冻结场地/车辆/车手/变速箱/流量/身份；在终局一次性提交。
- [排序与持久化](<src/ta_rank.c>)、[榜单接口](<src/ta_rank.h>)、[独立待同步候选队列](<src/ta_rank_outbox.h>)。
- [待机显示适配](<src/menu_ta_rank_ui.inc>)：实际 Unicode 名称、称号、等级、车型、调校与时间；不可用资源不伪装成 N/B/GUEST。
- [未来服务器契约](<server/ta_rank_service.py>)：纯 Python 标准库参考，不启动监听、不实现登录/TLS、不部署服务，不导入或改动既有 Ghost 服务。

**没有设备、Android 运行期、GPU 或真实在线服务通过的结论。**

## 原版口径与明确的移植策略

1. 原版 15 个赛道 ID，禁用 5/7/11，12 个有效赛道。待机连续循环为 `0,1,2,3,4,6,8,9,14,10,12,13`，不在被跳过的位置重复相邻赛道。UI 序号、原版 course ID、TA-stage slot 不可互换；初始相位保持移植版行为，不冒称已证明原版首次显示相位。
2. 每分区保存前 100 个真实成绩，待机显示前 10。车型与 P/H 混排，不臆造“原厂车分组”。同一车手仅严格更快才替换；相同或更慢不刷新时间戳。
3. 排序为毫秒升序、完成日期降序、精确同键的持久化插入序号降序；是顺位 1…100，不是共享并列名次。
4. 原版先做 **float32 × 1000.0f**，再截断。有效范围 1…1048574 ms；0 与 `0xfffff` 不是有效成绩。不能先转 double 再乘。`1048.575f` 本身实际略小，仍截断为 1048574；下一个更大的 float 才无效。
5. 原版默认占位显示 **19:59.999**，不是旧注释中的 9:59.999。默认行只供展示，不计真实人数、不伪造车手/运行元数据、不上传。
6. Native mode 6 也用于 Ghost 资格赛，因此不能仅凭模式号入榜。APP 正向确认普通 TA；只有实际状态 **8** 才是终局。状态 7 是 GoalWait，4…6 的 TIMEUP 不计入。
7. 原版最后一帧会把 elapsed 插值回退到实际终点检查点。APP 仅允许一次：状态 7/8、完整检查点前缀、elapsed bits 与最后 split bits 相等、回退不超过 1/60 秒加两 ULP；之后冻结该精确终点时钟。不是放开普通比赛中的倒退或修改物理。
8. 分区额外绑定完整规则哈希、物理 cohort 哈希及实际 traffic 0/1。当前物理 cohort 为 `SHA256(ASCII(car_ghost_physics_id()))`，不是整份平台 `.so` 的哈希；未来 verifier 注册表必须按这一明确语义识别，不可猜测。流量分组是明确的移植策略，不声称是原版原厂车类别。

冻结的字段包括真实原版 emCarModelID（唯一 canonical maker/car/color/type/gears/pack/paint 对应）、ECarType、有效 P/H、名称、称号、等级及原始场地六字。R35 仅由原版模型 ID 232…242 判定，使用原版 `menu_layout_ranking_ph`，直接显示独立 P/H 步数（例如24/10），不套普通马力换算。原版名称 Font8/24 advance，称号 Font1。称号表按声明 ID **首个匹配**查找：5149 无映射应为空，5150 命中第 5149 行，不按数组下标假造称号。

新榜不接收电影、故事、十连、VS、Ghost 资格/挑战/录像、退赛、TIMEUP、调试目标/时间/自动驾驶；道路重置、途中切换变速箱（包括切回）、车手/车辆/场地上下文变化会使本次新榜资格失效。`Official Machine` 当前没有完整 Native 原厂车实现，选择它不等于通过原厂/服务器核验，也不进入这个新榜。既有比赛和旧 PB/称号逻辑不因拒绝新榜资格而被改写。

## 本机身份与文件

全部 C 生产接口仅产生 `LOCAL_UNVERIFIED`。本机卡身份为 domain/slot/maker/car/birth 的稳定哈希；复制卡在同一本机目录保留身份，重启不丢去重。它不是原版 ID、全局唯一 ID、安装 UUID 或登录凭证。无注册卡的 GUEST 使用每次运行身份。attempt 使用独立 OS 熵和会话序号，不消耗原版 MT RNG。

Android 新榜仅使用 `Context.getDir("ta-ranking-v1", MODE_PRIVATE)` 的规范化内部私有目录，经既有 JNI 启动方法的独立末尾参数传入。旧外部 `wmmt` 目录、garage/PB 与管线缓存路径不迁移、不修改；不为兼容外部 FUSE 的权限外观而放松安全规则。内部目录不可用只停用新榜并显示错误，不阻止原有游戏启动。JNI 导出仍为 11 个，可选资源命名空间仍为 6 个；新目录不是第七种资源能力。

新文件名与旧存档完全分离：

```text
ta-ranking-v1-<rules64hex>-<physics64hex>.ctr
ta-pending-v1-<rules64hex>-<physics64hex>.ctq
```

- 固定 little-endian、128-byte header、196-byte records、CRC；不是 C struct dump。CRC 只检测损坏，不是认证。榜单最多 2400 行，候选队列最多 256 个 owner/course/traffic 单元。
- 使用可信绝对 app-private 目录、逐层 no-follow、非阻塞文件 open、regular/single-link/UID/权限和纳秒 stat 身份检查。损坏、异 cohort、FIFO、软/硬链接、不安全或变动文件保留，不自动修复或覆盖。
- 独立候选模型写入：O_EXCL 临时文件 → write → fsync → close → 目标身份复查 → renameat → 目录 fsync。rename 前失败保留旧文件及模型。`COMMITTED_UNSYNCED` 表示新文件已经发布，但目录持久性未确认，不能谎称回滚。
- 单可信所有者模型；stat 复查加 rename **不是**针对恶意并发目录写入者的原子 CAS。

候选队列独立于本机 top100：真实完赛即使排不进前 100，也可留下候选。每单元仅保留严格更快的待处理成绩；满 256 后拒绝新单元并保留全部旧数据，不静默丢弃、不宣称已同步。APP 先入队、再独立提交本机榜；任一文件损坏不阻止另一健康目的地保存，**不承诺跨文件事务**。无变化/重复提交不执行 fsync，不能消除先前的持久化不确定/失败提示。

## 以后接服务器时的边界

当前队列保存计时、检查点及配置元数据，**没有完整输入重放证据**。`local_upload_request(..., input_evidence=None)` 明确返回 `LOCAL_UNVERIFIED_EVIDENCE_MISSING`、无 payload、无伪造 input SHA/服务器回执。

- 严格 JSON 分区/原始 float bits/场地/元数据契约，拒绝重复键、超长、bool-as-int、客户端 `owner/player/rank/verified/path/auth` 等权威声明。
- 服务端身份必须来自可信登录适配器的 `TrustedPrincipal`，不能信本机 owner。该类型本身不是登录系统。
- 只有外部可信 timing verifier 对绑定的真实输入、规则/物理 cohort/场地与运行重放核验，给出完全匹配的实测结果后，参考服务才写全局榜。默认 verifier 缺失、失败、超时或不匹配，均保持 UNVERIFIED，全球榜为空。
- 全球 tie 日期采用服务端接收时间而非客户端自报日期，是未来服务的明确策略。客户端仍不能自行赋予服务器验证状态。
- v1 没有 C 端任意服务器快照导入、未经认证的 ack/dequeue 或自动清队列。后续还需真实登录/TLS、输入采集、受控重放、资源/频率限制、审计、备份及运营规则。这里没有部署这些服务。

## 原版资源与构建

新增的等级/handling/车型板来自原版资源，仍走同一个可选 `ghost-ui.bin` 能力，未新增第七命名空间/JNI 参数。显式新索引为 `arcade-ui-v5-index.tsv` / `WMMT-ARCADE-UI-5`。包内旧/新索引同时存在，或新索引损坏，都不会回退到另一份授权。旧 v4、旧 41 项索引和历史严格包验收逻辑保持分离。

私有显示元数据需从用户的原版生成，不把原始贴图/字体塞进源代码：

```bash
python3 -B tools/ranking_ui_tables.py \
  --source-root "${ORIGINAL_ROOT:?}" --tools-root tools \
  --output-directory "${BUILD_DIR:?}/ta-ranking"
export TA_RANK_PRIVATE_INCLUDE="${BUILD_DIR:?}/ta-ranking"
# 此目录必须绝对、规范化、位于源码快照之外；生成头固定SHA15a12c68…。
# 两个公开构建入口会校验并复制到构建私有目录，不能靠偶然CPATH或源码内同名头。
# ta_rank.c 与其他生产 C 一起编译；禁用 fast-math/finite-math-only，保持 -ffp-contract=off。
```

[专用严格 APK 检查器](<tools/verify_cinder_ranking_apk.py>) 要求独立的 v5 元数据、真实已批准 v4 bank（比较旧 83 个精灵及 17 个动画字节），以及原有九项 runtime/launcher/old41/dataset/paint 参考；不能用候选包自己的头部授权。

## 可复核的离线测试

```bash
export PYTHONDONTWRITEBYTECODE=1
export TMPDIR="${BUILD_TMP:?}"
clang -std=c11 -O2 -Wall -Wextra -Werror -ffp-contract=off \
  -fno-fast-math -I src test/ta_rank.c -lm -o "$TMPDIR/ta-rank-test"
"$TMPDIR/ta-rank-test"
PYTHONPATH=. python3 -B -m unittest discover -s tests -p test_ta_rank_service.py -v
```

[核心/文件/队列回归](<test/ta_rank.c>)覆盖 24 分区 2400 行、顺序与严格更快保留、float 边界、256 满队列、低于本机 top100 的候选、重复/冲突、重启、CRC/语义损坏、FIFO/链接/stat-ns、写入/fsync/close/rename 失败与已发布但未同步目录。普通编译及 UBSan 通过；[服务器契约测试](<tests/test_ta_rank_service.py>)16 项通过，只证明离线合约状态机，不证明真实云端反作弊。

另有真实重编译 Native 9 个完整终局/3 个自然超时、实际生产 APP → Native → 文件 → 待机快照、一次性完赛/辅助操作拒绝、真实资源加载、CPU draw-call 与完整三后端/SDK36 Java 构建证据。受控 Native 驾驶 fixture 显式预置 host steering filter，不是设备普通操控或公平比赛证明。ASan 在本机启动阶段挂起，不报告 ASan 通过。设备/GPU、网络服务与正式反作弊仍未验证。
