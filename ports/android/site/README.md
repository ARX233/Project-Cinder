# niceapi.net — Project Cinder 公共站点

`app.py` 是一个只用 Python 标准库的只读 Web 服务，直接读 `cinder-cloud` 的三个 SQLite，
对外提供设备验证、计时赛榜和店内鬼王榜。唯一会写入的是设备白名单，走
`server.device_registration` 官方入口。

## 运行形态

```
浏览器 ──HTTPS──> nginx (niceapi.net) ──> 127.0.0.1:8792 (cinder-web) ──┐
                                                                       ├─ /var/lib/cinder-cloud/timing-community.sqlite3
                                                                       ├─ /var/lib/cinder-cloud/shared-ghosts.sqlite3
                                                                       └─ /var/lib/cinder-cloud/approved-devices.sqlite3
Android ─HTTPS──> nginx (niceapi.net) ──> 127.0.0.1:8791 (cinder-cloud /v1/*)
```

站点进程以 `cinder-cloud` 用户运行，因此不需要改状态目录权限。

## 页面

| 路径 | 内容 |
| --- | --- |
| `/` | 首页、服务状态 |
| `/ta` | 计时赛榜（每条赛道前 100，只统计无交通车） |
| `/ghost` | 原版八区鬼王展台和列表，显示车手 ID、车型、马力及获得时间 |
| `/device` | 设备 ID 查询，未授权可自助开通 |
| `/admin` | 管理后台：登录后批准 / 撤销设备 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/status` | 代理 `/v1/capabilities`，用于首页状态灯 |
| GET | `/api/courses` | 按游戏顺序返回赛道 ID 和名称 |
| GET | `/api/ta?course=&limit=` | 榜单数据（固定 traffic=0） |
| GET | `/api/ghost` | 赛道鬼王及可用的车辆预览 |
| GET | `/api/device/<id>` | 设备授权状态 |
| POST | `/api/device/register` | 自助开通设备（每 IP 每小时 6 次） |
| POST | `/api/admin/login` | 口令换 Cookie（12 小时） |
| GET | `/api/admin/devices` | 已授权设备列表（需登录） |
| POST | `/api/admin/device` | `{"id","action":"allow"\|"revoke"}`（需登录） |

## 服务器布局

| 路径 | 说明 |
| --- | --- |
| `/opt/cinder-web/app.py` | 服务本体 |
| `/opt/cinder-web/static/` | 页面与样式 |
| `/etc/cinder-web/admin.json` | 管理口令的 PBKDF2 摘要（0640 root:cinder-cloud） |
| `/etc/systemd/system/cinder-web.service` | systemd 服务（127.0.0.1:8792） |
| `/etc/nginx/conf.d/zz-niceapi.conf` | niceapi.net 的 80/443 站点 |
| `/etc/letsencrypt/live/niceapi.net/` | Let's Encrypt 证书（自动续期） |
| `/etc/systemd/system/niceapi-cert-renew.{service,timer}` | 每天 00/12 点检查续期 |

`zz-` 前缀是有意的：conf.d 按文件名字母序加载，务必排在 `wechat-license.conf`
之后，否则 443 的默认 server 会变成 niceapi.net，用 IP 直连的现有客户端会拿到 421。

niceapi.net 的 443 块 include 了 `snippets/cinder-cloud-location.conf`，把 `/v1/*`
转给 8791。该 snippet 的正则必须包含 `device$`，否则 `/v1/device` 会落到 cinder-web
变成 404（设备鉴权全挂）。

## 运维

```sh
systemctl status cinder-web
systemctl restart cinder-web
journalctl -u cinder-web -n 50

# 换管理口令
python3 - <<'EOF'
import json, hashlib, secrets
pw = b'新口令'
salt = secrets.token_bytes(16); it = 240000
json.dump({"salt": salt.hex(), "hash": hashlib.pbkdf2_hmac("sha256", pw, salt, it).hex(),
           "iterations": it}, open('/etc/cinder-web/admin.json', 'w'))
EOF
systemctl restart cinder-web

# 手动续证
/opt/packora-certbot/bin/certbot renew --cert-name niceapi.net
```

## 与 cinder-cloud 的关系

站点只读数据库，不参与鉴权。设备授权写入 `approved-devices.sqlite3` 后，
`/v1/device` 立即生效（服务端每次请求都重新读该库）。

服务端已从 `--credentials` 切到 `--device-allowlist`：

```
ExecStart=/usr/bin/python3 -B -m server.cloud_service --state-dir /var/lib/cinder-cloud \
  --device-allowlist /var/lib/cinder-cloud/approved-devices.sqlite3 --port 8791 ...
```

回滚备份在 `/root/cinder-cloud.service.bak-20261108`。

## 车型与马力

`cars.json` 由 `tools/cardb.py` 从原版 `main` 提取（运行其自身函数，不是猜表）：

```sh
python3 tools/cardb.py "<arcade>/main" "<arcade>/data/car"   # -> tools/cars.json, src/cardb.h
```

`site/cars.json` 是从中裁出的 247 条 `model -> {label, short, hp}` 映射。
车牌里的 `model` 是 emCarModelID，`hp` 是该车原厂马力。

马力按原版 `GetHorsePower`（0x8568a44）的阶梯表换算：
power 0 用原厂值，1..24 依次是 360/400/420/450/470/500/530/550/580/600/620/640/660/680/700/720/740/760/780/800/810/815/820/825。

## 鬼王展台素材

`build_crown_art.py` 从原版的 `menu_g_crown_atract.anm` 和精灵表导出八区牌面，再用本地转换好的车辆包生成转台 WebP 和静态图。
例如目前 C1 鬼王的车辆可用以下命令生成，九个数字依次是车型、自定义车色、包围、后视镜、尾翼、引擎盖、轮圈、霓虹和贴花 ID。

```sh
python3 site/build_crown_art.py --out /path/to/staging --arcade /path/to/arcade \
  --data /path/to/private/data --generated-src /path/to/private/generated-src \
  --car 77 0 1 0 0 2 0 0 0
```

自定义车色需要另传 `--paint-bank`。只部署生成的 WebP 到 `static/crown/`。
网站从当前鬼王录像读取改装组合，优先展示对应预览。尚未渲染的组合会展示同车型与同原厂颜色的静态图，并标明「原厂车型预览」。原厂车型图可一次生成：

```sh
python3 site/build_crown_art.py --out /path/to/staging --data /path/to/private/data --stock
```

## 已知边界

- 榜单是**社区成绩**，服务端不做重放核验（`ta_verifier_available:false`），页面已标注。
- 网页和游戏联机模式共用八区鬼王记录。网页每 15 秒刷新可见页面。计时赛榜首和普通共享化身不改变席位。
- 当前鬼王录像独立保留，直到被下一位玩家击败。网页只返回展示数据，录像由获准的游戏设备下载。
- 自助开通是即时生效的，靠每 IP 每小时 6 次限速兜底；如需改成人工审核，删掉
  `/api/device/register` 分支即可。
