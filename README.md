# 1688 以图搜货 API

本项目提供两个服务能力：

1. PC 浏览器通过油猴脚本手动同步 1688 Cookie 到 Linux。
2. 其他应用通过带 API 密钥的 HTTP 接口上传图片文件或提交图片链接，获取 1688 图片搜索链接。

Cookie 使用 HMAC-SHA256 验签后加密保存。远程图片搜索使用独立 Bearer API 密钥，两个接口不共用认证凭证。

## 运行要求

推荐方式：

- Linux
- Docker Engine，启用 IPv6
- Docker Compose v2
- 宿主机具备可用的 IPv6 出口
- 已配置 HTTPS 的域名
- Nginx、Caddy 或其他 HTTPS 反向代理
- 支持 `GM_cookie` 的 Tampermonkey 或 Violentmonkey
- PC 浏览器已登录 1688

非容器方式需要 Python 3.9.2+，推荐 Python 3.12。

## 目录说明

```text
compose.yaml                           Docker Compose 配置
Dockerfile                             Python 3.12 容器镜像
main.py                                命令行图片上传入口
lib/ali1688/                           1688 请求和签名
lib/cookie_sync/                       Cookie 接收、认证和加密存储
lib/image_api.py                       API 密钥和图片文件校验
lib/image_download.py                  图片链接安全下载和 SSRF 防护
userscripts/ali1688-cookie-sync.user.js  PC 浏览器油猴脚本
deploy/                                systemd 和 Nginx 示例
runtime/                               加密 Cookie 和临时文件，不纳入 Git
```

## Docker Compose 部署

### 1. 创建配置

```bash
cd /opt/1688-crawler
cp .env.example .env
```

生成三个不同的随机密钥：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

编辑 `.env`：

```ini
COOKIE_SYNC_SHARED_SECRET=第一条随机密钥
COOKIE_ENCRYPTION_KEY=第二条随机密钥
ALI1688_API_KEY=第三条随机密钥

ALI1688_COOKIE_FILE=/app/runtime/ali1688.cookies.enc
ALI1688_UPLOAD_TEMP_DIR=/app/runtime/uploads
COOKIE_SYNC_MAX_CLOCK_SKEW=300
ALI1688_MAX_IMAGE_MB=10
```

三个密钥用途如下：

- `COOKIE_SYNC_SHARED_SECRET`：油猴脚本同步 Cookie 时进行 HMAC 验签。
- `COOKIE_ENCRYPTION_KEY`：加密 Linux 上保存的 Cookie 文件。
- `ALI1688_API_KEY`：远程图片搜索 API 的 Bearer 密钥。

三个值必须不同，每个值至少 32 个字符。

设置文件权限并创建持久化目录：

```bash
chmod 600 .env
mkdir -p runtime/uploads
chmod 700 runtime runtime/uploads
```

容器使用 UID/GID `10001`。Linux 上需要赋予运行目录写权限：

```bash
chown -R 10001:10001 runtime
```

### 2. 拉取并启动

`compose.yaml` 为项目 bridge 网络启用了 IPv6。Docker daemon 也必须开启 IPv6，修改 daemon 配置后需要重启 Docker。

首次启动或启用 IPv6 后，需要重建项目网络：

```bash
docker compose down
docker compose pull
docker compose up -d --force-recreate
```

执行 `docker compose down` 不会删除挂载在宿主机 `runtime/` 中的 Cookie 文件。禁止附加 `-v`，否则可能删除其他命名卷。

查看状态：

```bash
docker compose ps
docker compose logs --tail=100 ali1688-api
```

服务仅映射到宿主机 `127.0.0.1:8765`，不会直接开放公网端口。

停止服务：

```bash
docker compose down
```

更新镜像并重建容器：

```bash
docker compose pull
docker compose up -d
```

Cookie 文件保存在宿主机 `runtime/ali1688.cookies.enc`。执行 `docker compose down` 不会删除该文件。

验证容器 IPv6：

```bash
docker compose exec ali1688-api python -c "import socket; print([x[4][0] for x in socket.getaddrinfo('h5api.m.1688.com', 443, type=socket.SOCK_STREAM)])"
```

运行镜像通过 `/etc/gai.conf` 对双栈目标优先使用原生 IPv6，并保留 IPv4 回退。该配置用于避开部分服务器到 1688 IPv4 CDN 的 TLS 链路异常。

## HTTPS 反向代理

### Nginx

修改 `deploy/nginx-ali1688-cookie-sync.conf` 中的域名和证书路径，然后安装配置：

```bash
nginx -t
systemctl reload nginx
```

示例配置开放以下路径：

- `GET /healthz`
- `POST /api/cookie-sync`
- `POST /api/v1/image-search`
- `POST /api/v1/image-search/url`

限制规则：

- Cookie 同步请求体最大 64 KB。
- 图片搜索请求体最大 11 MB。
- 两个接口使用独立的每 IP 请求频率限制。
- Nginx 访问日志关闭，避免长期记录鉴权请求元数据。
- 其他路径返回 404。

### Caddy

```caddyfile
sync.example.com {
    log {
        output discard
    }

    @health path /healthz
    reverse_proxy @health 127.0.0.1:8765

    @sync {
        path /api/cookie-sync
        method POST
    }
    reverse_proxy @sync 127.0.0.1:8765

    @search {
        path /api/v1/image-search /api/v1/image-search/url
        method POST
    }
    reverse_proxy @search 127.0.0.1:8765

    respond 404
}
```

Caddy 示例不包含速率限制。生产环境应通过插件、上游 CDN 或防火墙增加限流。

## 安装油猴脚本

1. 打开 `userscripts/ali1688-cookie-sync.user.js` 并安装脚本。
2. 打开并登录 `https://www.1688.com/`。
3. 从脚本菜单执行“配置同步接口”。
4. 输入 `https://实际域名/api/cookie-sync`。
5. 执行“配置共享密钥”。
6. 输入 `.env` 中的 `COOKIE_SYNC_SHARED_SECRET`。
7. 执行“同步 1688 Cookie 到 Linux”。

脚本使用 `@connect *`，可配置任意 HTTPS 同步域名，无需修改脚本元数据。

脚本不会自动同步。Cookie 只在用户点击菜单后发送。

`document.cookie` 无法读取 HttpOnly Cookie，因此脚本使用 `GM_cookie`。脚本管理器必须支持该 API。

## Cookie 同步认证

同步请求包含：

- `X-Sync-Timestamp`：Unix 秒级时间戳。
- `X-Sync-Nonce`：一次性随机数。
- `X-Sync-Signature`：HMAC-SHA256 签名。

签名原文：

```text
时间戳\n随机数\n请求体SHA256
```

服务端校验：

- 时间偏差默认不超过 300 秒。
- 随机数格式正确且没有被使用。
- HMAC 签名匹配。
- Cookie 只能属于 1688 域名。
- 必须包含 `_m_h5_tk` 和 `_m_h5_tk_enc`。

PC 和 Linux 必须启用准确的系统时间，建议启用 NTP。

## 远程图片搜索 API

### 接口

支持两种请求方式：

```text
POST /api/v1/image-search       上传图片文件
POST /api/v1/image-search/url   提交图片链接
```

### 鉴权

```http
Authorization: Bearer <ALI1688_API_KEY>
```

远程调用方只需要获得 `ALI1688_API_KEY`，不应获得 Cookie 同步密钥或 Cookie 加密密钥。

### 图片文件请求格式

请求使用 `multipart/form-data`，图片字段名固定为 `image`。

支持格式：

- JPEG
- PNG
- WebP

默认最大图片大小为 10 MB，可通过 `ALI1688_MAX_IMAGE_MB` 调整，允许范围为 1-50 MB。

服务端根据文件头识别真实图片格式，不信任上传文件名。临时文件在请求成功或失败后都会删除。

### 图片文件 curl 调用

```bash
curl --fail-with-body \
  -X POST 'https://sync.example.com/api/v1/image-search' \
  -H 'Authorization: Bearer 你的ALI1688_API_KEY' \
  -F 'image=@./product.jpg;type=image/jpeg'
```

成功响应：

```json
{
  "image_id": "1688返回的图片ID",
  "search_url": "https://s.1688.com/youyuan/index.htm?...",
  "image_type": "jpeg",
  "image_bytes": 123456
}
```

### 图片链接调用

请求使用 JSON，字段名固定为 `image_url`：

```bash
curl --fail-with-body \
  -X POST 'https://sync.example.com/api/v1/image-search/url' \
  -H 'Authorization: Bearer 你的ALI1688_API_KEY' \
  -H 'Content-Type: application/json' \
  --data '{"image_url":"https://images.example.com/product.jpg"}'
```

图片链接必须满足以下条件：

- 使用 HTTPS。
- 不得包含 URL 用户名或密码。
- 域名解析结果必须全部为公网 IP。
- 禁止访问本机、内网、链路本地和保留地址。
- 最多允许 3 次重定向，每次重定向都会重新执行地址安全校验。
- 下载过程按块读取，并遵守 `ALI1688_MAX_IMAGE_MB` 限制。
- 只接受真实内容为 JPEG、PNG 或 WebP 的响应。

### Python 文件上传调用

```python
import requests

with open("product.jpg", "rb") as image_file:
    response = requests.post(
        "https://sync.example.com/api/v1/image-search",
        headers={"Authorization": "Bearer 你的ALI1688_API_KEY"},
        files={"image": ("product.jpg", image_file, "image/jpeg")},
        timeout=60,
    )

response.raise_for_status()
result = response.json()
print(result["search_url"])
```

图片链接 Python 调用：

```python
import requests

response = requests.post(
    "https://sync.example.com/api/v1/image-search/url",
    headers={"Authorization": "Bearer 你的ALI1688_API_KEY"},
    json={"image_url": "https://images.example.com/product.jpg"},
    timeout=90,
)
response.raise_for_status()
print(response.json()["search_url"])
```

### 状态码

- `200`：搜索成功，返回搜索 URL。
- `401`：未提供 API 密钥或密钥错误。
- `422`：文件或图片链接无效、格式不支持、MIME 不匹配或图片过大。
- `502`：1688 Cookie 无效、上游接口不可达或上游响应异常。

接口不会返回 Cookie、密钥或 1688 上游的完整响应。

## 健康检查

```bash
curl https://sync.example.com/healthz
```

响应：

```json
{"status":"ok"}
```

健康检查只表示服务进程正常，不表示当前 Cookie 有效。

## 命令行上传

Docker 容器内执行：

```bash
docker compose exec ali1688-api python main.py /app/runtime/example.jpg
```

该图片必须先放入挂载的宿主机 `runtime/` 目录。

非容器方式：

```bash
set -a
. /etc/ali1688-cookie-sync.env
set +a
.venv/bin/python main.py data/down.jpeg
```

成功后只输出 1688 图片搜索 URL。

## 非 Docker 安装

使用 Poetry：

```bash
poetry install
```

使用 venv：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install requests fastapi 'uvicorn[standard]' cryptography pydantic python-multipart
```

服务启动命令：

```bash
.venv/bin/uvicorn lib.cookie_sync.api:create_app --factory --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
```

systemd 示例位于 `deploy/ali1688-cookie-sync.service`。

## 测试

```bash
poetry install
poetry run pytest
```

测试使用假上传器和假图片下载器，不请求真实 1688 接口，不使用真实 Cookie。

## 安全要求

- Docker 端口只绑定宿主机 `127.0.0.1`。
- 公网入口必须使用有效 HTTPS 证书。
- 三个密钥必须独立，禁止重复使用。
- 不记录 `Authorization`、同步签名头、请求体、Cookie 或密钥。
- 不提交 `.env`、`runtime/` 或服务器环境变量文件。
- 远程调用方只分发 `ALI1688_API_KEY`。
- Cookie 泄露时，立即退出 1688 登录并重新登录。
- API 密钥泄露时，轮换 `ALI1688_API_KEY` 并重启容器。
- 轮换 `COOKIE_ENCRYPTION_KEY` 后旧 Cookie 文件无法解密，需要删除旧文件并重新同步。
