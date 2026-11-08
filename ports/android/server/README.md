# Cinder 云端化身与计时赛服务

`cloud_service.py` 提供一个 HTTP 入口。化身分享和计时赛共用同一账号认证，分别用 SQLite 保存数据。社区计时榜接受客户端原生完赛元数据并标记为未核验。正式计时榜和世界王冠需要可信的服务端重放核验器。

## 生产运行

- `deploy/` 提供独立的 systemd 服务、每日快照定时器和 Nginx HTTPS 配置。后端监听 `127.0.0.1:8791`，由反向代理提供证书、请求大小与速率限制。服务异常退出时由 systemd 重启。`GET /v1/capabilities` 可用来检查公网链路和已启用的能力。
- 化身默认保留 90 天，最多 1,000 条，每账号最多 128 条。新录制到达上限时先淘汰最早更新的录制。查询和下载不延长寿命。进程启动及之后每五分钟执行清理，并回收 SQLite 空闲页。关联的防守战报随录制过期，未关联到过期录制的战报也最多保留 90 天。90 天为 Cinder 策略。[3DX+ 官方 FAQ](https://bandainamco-am.co.jp/am/vg/wanganmaxi3dxplus/faq/h.php)
- 社区计时赛按认证账号、车卡、赛道和交通设置保留个人最佳。每账号上限 384 条，全库上限 20,000 条。客户端在服务器确认提交摘要后才移除待上传项目，断线时继续保留本地成绩。
- 生产化身数据库的页数上限对应 448 MiB，社区计时数据库为 32 MiB。写入保留至少 512 MiB 文件系统可用空间。备份保留最近三份独立的本机 SQLite 快照，每份通过 `quick_check` 后才发布。

## 本地启动

在 `ports/android` 目录运行。提前创建状态目录和凭证文件。凭证是由服务运营方管理的 JSON 对象，键为随机的 32–128 字符 Base64URL bearer token，值为稳定的服务器账号标识。每位玩家使用各自的随机 token。用 `secrets.token_urlsafe(32)` 生成凭证，将文件权限设为 `0600`。每次改动凭证文件后重启服务。

```sh
python3 -B -m server.cloud_service \
  --state-dir /path/to/cinder-state \
  --credentials /path/to/cinder-credentials.json
```

默认监听 `127.0.0.1:8080`。直接绑定非回环地址时需提供 `--tls-cert` 和 `--tls-key`，或将回环监听置于 HTTPS 反向代理后。非能力探测请求都使用 `Authorization: Bearer <token>`。状态目录由单个服务实例持有，保存 `shared-ghosts.sqlite3`、`timing-community.sqlite3` 和独立的正式 `timing.sqlite3`。化身清理可用 `--ghost-retention-days`、`--ghost-max-records` 和 `--ghost-max-per-account` 配置。

## Android 设备登记

新版 Android 在启动器的「选择资源 → 联网设备登记」提供可复制的 32 位设备 ID。ID 绑定本次安装，应用更新和资源包替换保留它。卸载或清除应用存储后会生成新 ID。网站只收设备 ID。手机通过 HTTPS 使用安装时生成的私有凭据验证，服务端可据此计算同一个 ID。

Android 的正式服务地址在 `android/java/com/wmmt/port/CloudDevice.java` 配置。`CLOUD_ORIGIN` 填云端 API 的 HTTPS 域名，`ONLINE_VS_DOMAIN` 单独填 WVS4 房间服务器的域名。留空表示相应服务尚未配置。Android 的设备登记只用于云端化身和计时榜。局域网与房间对战使用独立协议。

服务端以 `--device-allowlist` 替换 `--credentials`，并将 `/v1/device` 转发到该服务。两种认证模式互斥。登记网站批准 ID 后，可在服务端调用 `server.device_registration.set_approved(path, device_id, True)`，或者由运营人员运行以下命令。批准与撤销实时生效。

```sh
python3 -m server.device_registration allow /path/to/cinder-state/approved-devices.sqlite3 "$DEVICE_ID"
python3 -m server.cloud_service --state-dir /path/to/cinder-state \
  --device-allowlist /path/to/cinder-state/approved-devices.sqlite3
python3 -m server.device_registration revoke /path/to/cinder-state/approved-devices.sqlite3 "$DEVICE_ID"
```

原有 Bearer 账号和设备账号使用各自的数据身份。启用设备登记会保留原有云端记录，旧账号私有记录不会自动转移到新设备账号。

## HTTP v1

| 方法和路径 | 内容 |
| --- | --- |
| `GET /v1/device` | 设备登记模式的认证检查。通过时返回设备 ID 和 `approved:true`。 |
| `GET /v1/capabilities` | 免认证。分别返回化身分享、世界王冠、计时榜单及计时核验器的能力。 |
| `POST /v1/ghosts?area=0` | 请求体为 `application/octet-stream` 格式的完整 `W3GCROWN` v1 容器，上限 395,540 字节。首传返回 201，同一账号和区域重复提交同一内容返回 200 及同一记录。可选 `X-Cinder-Card-ID` 头为 32 位小写十六进制的私有存档键。 |
| `GET /v1/ghosts?physics_sha256=<hex>&limit=20` | 返回 `ghosts` 数组和 `next_cursor`。可选 `area=0..7`、`limit=1..50`、`cursor` 和 `others=1`（排除当前账号）。`name_hex` 接受原版最多五个字符的 UTF-8 十六进制串，按字形子串匹配。`id` 可定位旧的共享记录。常规列表按账号、存档、物理版本及赛道分组，仅显示各组最新记录。 |
| `GET /v1/ghosts/<id>` | 下载原始容器字节，`X-Content-SHA256` 与 `ETag` 提供内容摘要。 |
| `POST /v1/ghosts/<id>/battles` | 客户端上报比赛结果。34 字节小端请求体依次是 16 字节随机比赛标识、挑战者胜负（1/0）、车型（u8）、马力（u16）、防守化身的领先距离（i32 米，`INT32_MIN` 表示未知）和补零至五字符的 UTF-16LE 名字。同账号相同内容重传不重复记入。 |
| `GET /v1/ghosts/defense?card_id=<hex>` | 当前认证账号下指定存档的总场次、胜场及最多八条最近的防守战绩。 |
| `POST /v1/ta/community` | 236 字节 `CTA1` 记录。前四字节为标识，接着是两组 32 字节规则和物理摘要，再接本地计时赛行的前 168 字节。原版卡号与本地排名省略。响应返回 `sha256` 和 `verified:false`。 |
| `GET /v1/ta/community` | 使用与正式榜相同的四个分区参数，返回 `CTB1`、小端记录数和至多十条 `CTA1` 社区记录。 |
| `GET /v1/ta/leaderboard` | 使用 `rules_sha256`、`physics_sha256`、`course_id` 和 `traffic` 查询已核验成绩。 |
| `POST /v1/ta/attempts` | 由服务运营方注入可信核验器后启用。请求体依次为四字节大端 JSON 长度、计时赛契约 JSON 及二进制输入证据。核验器缺失时返回 503。 |

化身返回字段为 `id`、`sha256`、`bytes`、`area`、`physics_sha256`、`display_name`、`raw_model`、`raw_ramp`、`route`、`created_ms` 和 `verified`。ID 是服务端生成的 32 位小写十六进制字符串。服务端验证容器、检查赛道区域和录制采样的语法，并原样保存数据。客户端仍须使用原生引擎检查赛道和回放兼容性。共享化身与客户端上报战绩的 `verified` 恒为 false。服务端通过已共享录制确定防守账号和存档，认证挑战者身份，防守记录仅向其所属账号返回。普通化身可包含已验证原生赛道字段的计时赛录制，世界王冠仍由下方的独立可信核验契约管理。

回环回归覆盖认证、跨账号分享、原样下载、并发重传、重启、翻页、坏数据及计时赛入口。

```sh
python3 -B -m unittest discover -s tests -p test_cinder_cloud_http.py -v
```

# 未来云端王冠契约与参考状态存储

**这不是已上线云服务，也不是排行榜、真实服务器反作弊或第五模式游戏实现。**
这一部分描述尚未接入 HTTP 服务的可信王冠核验契约和 SQLite 状态存储。
用户选定的政策是：**胜者经服务器可信重放核验后夺位**，不是客户端上报胜利即夺位。
“全服高手作为店内王者”的未来数据来源也尚未接入。

## 信任边界

- `GhostStore` 是未来服务器内部 API，不是可以直接暴露给客户端的 Python RPC。
- `TrustedPrincipal(subject, auth_source)` **只能由可信 auth adapter 在认证之后构造**。
  它是内部类型标记，不是签名、登录机制或无法伪造的 Python 安全对象；持有服务器进程
  执行权限的调用者天然属于可信边界。上传 JSON 不接受 `player_id`/`auth`/权限声明。
  auth adapter 必须把各登录来源映射到稳定、唯一、不可冒用的服务器用户 ID。
- `TrustedAdministrator` 仅用于可信初始 seed。空分区只能经管理/可信 seed 流程建立首位
  王者，普通玩家不能通过“赢空库”抢占；已有王者不能调用 seed 覆盖。谁有 seed 权限、
  seed 如何来自合法高手数据及其管理审计，必须由将来的运营/auth 集成决定。
- `ReplayVerifier.verify(VerificationRequest, deadline_monotonic=...)` 是**服务器注入的可信接口**。
  必须自行检查原引擎版本、规则/物理/赛道身份、完整输入证据、双方原始化身与真实胜负。
  默认 `verifier=None`，返回 `UNVERIFIED / verifier_unconfigured / http_status=503`，绝不授位。
  没有任何默认通过验证器或 mockAlwaysPass 运行入口。
- SHA-256 仅绑定字节身份/完整性；符合格式、checksum 正确、客户端说 `win=true`、
  上传 `rank`/`verified` 都不是服务器反作弊证据。后三种字段直接拒绝。

## 数据模型 v1

每个独立王者分区的完整 identity：

```json
{
  "course_id": "server-course-id",
  "route_id": "server-route-id",
  "rules_sha256": "<64 lowercase hex>",
  "physics_sha256": "<64 lowercase hex>"
}
```

四个字段全部参与主键；course/route/rules/physics 任一个不同即为不同王者。
服务器必须以可信 registry 把这些标识映射到真实赛道资源、规则、物理及引擎构建，不能
把客户端自报的哈希当作真实引擎身份。本 reference 不包含该 registry 或资源。
course/route 和内部用户/adapter/verifier 标签使用 ASCII
`[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`；digest 必须是 64 个小写十六进制字符。

### 原始数据边界

- `original_blob_format = "opaque-original070426a"` 是暂定的不透明数据标签，不是新造的
  原生 C struct，也不声明当前已恢复该格式。服务器不把原游戏数据改成 Python 私有回放格式。
- 原始化身 `original_blob: bytes` 与 `input_evidence: bytes` 分别传入；输入证据当前也不透明，
  将来由原引擎 server verifier 定义/解析其完整性与时序，不凭本 reference 猜字段。
- 不接受文件名、任意路径、URL、base64 文件指令，不做 `eval/exec/pickle`，不执行上传内容。
- 当前限制：claim JSON 1–8192 bytes；原始 blob 1–4 MiB；input evidence 1–8 MiB。
  transport adapter 仍须在读取/解码前施加请求总长、并发、速率和流式上传限制。
- `metadata` 只接受 `{}` 或 `{"display_name":"..."}`；名字 1–64 个可打印字符、UTF-8
  最多 128 bytes，拒绝控制符、代理码及 `/`、`\`。metadata 不承载性能、排名或权限。

### 签发挑战：`issue_challenge(principal, identity, ttl_ms=300000)`

`ChallengeSnapshot.to_dict()` 的字段：

| 字段 | 来源/意义 |
| --- | --- |
| `schema_version` | 固定整数 1 |
| `challenge_id` | 服务器安全随机签发，不接受客户端自选 |
| `player_id` | 可信 principal 的 subject |
| `identity` | 上述完整四元身份 |
| `king_revision` | 签发时固定的王者 revision（从 1 单调递增） |
| `king_blob_sha256` | 签发时原始王者 blob 的 SHA-256 |
| `original_blob_format` | 固定 `opaque-original070426a` |
| `king_player_id`, `king_metadata` | 固定旧王者显示信息，不是客户端成绩 |
| `issued_at_ms`, `expires_at_ms` | 服务器 Unix 毫秒整数；默认 TTL 5 分钟，最大 1 小时 |

`challenge.king.blob` 是对应固定原始 blob bytes，单独交付，不放进 JSON。
内部同时固定旧王者输入证据 digest、来源、记录时间与 originating receipt。
challenge 及其 king/identity/metadata 均为 frozen 值对象；数据库保留完整旧 blob 快照。
`get_challenge(principal, challenge_id)` 只允许挑战所属用户读取历史固定快照。
取消状态独立保存，不改写签发快照；到期上界是排他的，`now >= expires` 即过期。
服务器时钟倒退到 `issued_at_ms` 之前也拒绝新 claim。

### 提交：`submit_claim(principal, payload_bytes, original_blob, input_evidence)`

唯一公开 wire JSON 解析器为 `parse_claim_json(bounded_bytes)`：UTF-8、精确字段集合、拒绝
重复 key（包括嵌套）、错误类型、bool 冒充整数、所有浮点数/非 finite 数字/超大整数、
未知字段和路径字段。没有通用反序列化/文件打开入口。

JSON **恰好**包含以下字段，所有字段必填：

```json
{
  "schema_version": 1,
  "claim_id": "<client idempotency token>",
  "challenge_id": "<server-issued challenge>",
  "nonce": "<fresh client nonce>",
  "old_king_revision": 1,
  "identity": {
    "course_id": "server-course-id",
    "route_id": "server-route-id",
    "rules_sha256": "<64 lowercase hex>",
    "physics_sha256": "<64 lowercase hex>"
  },
  "king_blob_sha256": "<pinned king blob digest>",
  "original_blob_format": "opaque-original070426a",
  "original_blob_sha256": "<submitted original blob digest>",
  "input_evidence_sha256": "<submitted input evidence digest>",
  "metadata": {}
}
```

claim_id/challenge_id/nonce：ASCII `[A-Za-z0-9_-]{16,96}`。client 应使用随机且新鲜的
claim_id/nonce。数值只接受精确整数，revision 范围 1–`2^53-1`，便于未来原生/JSON 对接。

服务端按可信用户匹配 challenge，再检查 old revision、完整 identity、pinned king SHA、
提交的两份 bytes 与两份 digest；原始 bytes/输入证据及 metadata 都属于幂等绑定。
`VerificationRequest.binding_sha256` 是规范化 JSON 的 SHA-256，其内容为服务器用户 ID、
完整固定 challenge 描述与整个 claim；它同时绑定这些 digest，而非从客户端接收 request hash。
可信 verifier 必须返回 `ReplayVerdict`，其 binding digest 与本次请求完全一致，outcome 必须是
`ReplayOutcome.WIN / LOSS / INVALID`，并带 bounded verifier_id/verifier_revision。
普通字典/布尔“验证通过”不能作为 verdict。

## 状态与事务

1. 事务保留 claim_id、challenge、用户 nonce 和原始证据；内部状态 `VERIFYING`。
2. 释放数据库/Python 操作锁后调用 trusted verifier，允许不同挑战并行验算。
3. 重新开事务，重查取消/过期及当前 king，生成最终 receipt，并与可能的 king CAS 一起提交。

| receipt.status | 语义 | 默认 HTTP 映射 |
| --- | --- | --- |
| `UNVERIFIED` | 未配置、异常、超时、错误 verdict 或中断；不改变王者 | 503 |
| `UNVERIFIED` + `replay_invalid` | trusted verifier 判为无效回放；不改变王者 | 422 |
| `VERIFIED_LOSS` | trusted verifier 判负；不改变王者 | 200 |
| `PROMOTED` | 核验获胜，且当前王者仍是 pinned revision/SHA；CAS 夺位 | 200 |
| `VERIFIED_WIN_STALE` | 核验确实战胜旧快照，但已有新王者；记胜而不覆盖 | 200 |
| `REJECTED` | 验算期间被取消或过期；不授位 | 410 |

`http_status` 只是参考 adapter 映射，没有实际 HTTP 服务。预检失败抛出 `ContractError(code,
http_status)`，如过期/取消 410、challenge 不属于用户 404、绑定/幂等/nonce 冲突 409。

Receipt 包含：schema_version、receipt_id、claim_id、challenge_id、player_id、identity、
request_sha256、old_king_revision、king_blob_sha256、original_blob_sha256、input_evidence_sha256、
status、reason、verified_win、promotion_applied、resulting_king_revision、recorded_at_ms、
http_status、verifier_id/verifier_revision（未核验可为 null）。王者保存 originating_receipt_id。

- 同 claim_id + 同可信用户 + 同规范化内容/证据只返回**完全相同的最终 receipt**，不重复验算
  或夺位；在验算中的完全相同请求等待同一结果。空白/JSON key 顺序不改变幂等语义。
- 同 claim_id 改任何绑定字段/证据或换用户：409。每个 challenge 最多一个被接纳的 claim。
- `(player_id, nonce)` 唯一，跨该用户的新 challenge 重放也 409；未核验失败的 accepted claim
  也消耗 nonce。不同用户的 nonce 空间独立。
- 完全相同的重复提交即使之后过期，也能取回既存 receipt；这不是接受一个新的过期 claim。
  后来补上 verifier 不会重审过去的 `UNVERIFIED` claim；如需重试必须重新签发挑战。
- 两个挑战同 revision 都经 verifier 判胜时，恰好一个 CAS 授位，另一个得到 stale win。
  旧快照不会被替换为新 king 去偷偷重算；新挑战才绑定新 revision。
- 取消/到期在预检及最终事务检查。final receipt 不能被之后的取消 retroactively 改写。
- verifier 异常、错误类型/绑定、超时、损坏 blob 都不授位；不把异常字符串/路径写入 receipt。
- king CAS 与 final receipt 更新在同一事务，receipt 写失败会回滚 king。存储异常令实例停止
  接受新工作，必须排查并重开；不会继续在不确定状态下授位。

## 时间限制与持久性边界

**同步 reference 的 deadline 不是进程隔离。** 默认 verifier 预算 5 秒（配置范围 >0–60 秒）；
adapter 收到 monotonic deadline，reference 检查迟到返回并 fail closed，`TimeoutError` 也不授位。
但任意 in-process Python adapter 若永久挂起，reference 无法安全强制打断，重复请求也会等待。
生产必须使用受限、可终止的独立原引擎 worker/队列、资源预算与外层 deadline，不能把这里的
迟到检查宣传为可靠 worker timeout。`close()` 在存在 active verification 时明确拒绝。

- 默认 `GhostStore()` 使用 `:memory:`，进程结束即丢失数据。
- 需要本机持久化时，只有可信服务器配置可传入绝对 `db_path`。JSON 永不选择数据库路径；
  该文件及父目录必须受管理员权限保护，不能由客户端提供/替换，不支持打开不可信数据库。
- SQLite DELETE journal + FULL synchronous + 事务保存 kings/challenges/claims、固定快照、
  原始提交 bytes/输入证据与 receipt。保留 exclusive lock 至 close：**每个文件只允许一个
  活跃 store owner**，不是多进程/多机 HA 服务；同 owner 内不同挑战可并发验算。
- 进程在保留 claim 后、最终提交前崩溃，重开时把该 reservation 的预留 receipt 固定为
  `UNVERIFIED / verification_interrupted / 503`，不重跑 verifier、不猜测授位。final king/receipt
  提交前后由 SQLite 原子性决定；不承诺硬件损坏、文件篡改或不可靠文件系统下的数据恢复。
- 当前没有总容量/用户配额、到期记录清理、云 blob 对象存储、备份恢复、加密、审计系统、
  schema migration、消息队列或 distributed CAS。复制快照会占空间，不能直接当作大规模部署。

## 尚待接入（生产前置条件）

可信 auth adapter/管理员授权与审计；公网 HTTP/TLS/会话及重放保护；服务器规则/物理/赛道
registry；限流/权限/配额；真实 cloud blob 存储与 immutable retention；确定性原引擎 server
验算及可终止隔离 worker；持久化运维/监控/迁移。客户端 pending-claim UI 应把本地赢、待提交、
未核验、已核验但 stale、真正 `PROMOTED` 分开显示，不得把 `UNVERIFIED` 当“已成为全服王者”。

## 仅主机协议/状态模型测试

在 workspace 根目录执行（无需安装包、无需外网）：

```sh
TMPDIR="$PWD/tmp" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s source/tests -p test_ghost_cloud_contract_host.py -v
```

测试只使用 synthetic blob/input 和 **test-only MockVerifier**。覆盖同版本双挑战并发 CAS、
并发重复、幂等冲突、nonce、旧快照、过期/取消（含验算期间）、异常/未配置/超时/错误 verdict、
损坏 bytes、receipt 写失败原子回滚、落盘重开/中断恢复/第二 owner 拒绝，以及所有窄 JSON 边界。
**通过测试的 authority 是协议和状态模型，不是真实原引擎胜负核验、反作弊或云端已上线证明。**
