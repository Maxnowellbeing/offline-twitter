# Offline Twitter

一个自托管的离线 Twitter/X 阅读器，通过 GraphQL API 抓取推文和媒体内容，提供类似 Twitter 的暗色主题界面进行浏览。

> **声明：本项目由 AI（Claude）编写，包括全部后端逻辑、前端界面、部署脚本及文档。**

## 功能特性

- **仿 Twitter 界面** - 暗色主题，时间线流、推文卡片、图片/视频展示
- **关注管理** - 添加/移除关注的博主，支持自动定时抓取
- **媒体库** - 按图片/视频筛选浏览所有媒体，支持 Lightbox 全屏查看
- **全文搜索** - 搜索推文内容
- **用户主页** - 查看单个博主的推文和个人信息
- **收藏功能** - 点击爱心图标收藏推文，独立页面查看所有收藏
- **自动刷新** - 后台定时抓取新推文（默认30分钟）
- **删除保护** - 删除的推文不会在下次刷新时重新下载
- **代理支持** - 通过 HTTP 代理访问 Twitter API

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python Flask + SQLite |
| 前端 | HTML/CSS/JavaScript |
| API | Twitter GraphQL API |
| 代理 | xray-core (Docker) |
| 部署 | systemd + SSH |

## 快速开始

### 环境要求

- Python 3.10+
- Flask (`pip install flask flask-cors`)
- Twitter 账号的 AUTH_TOKEN 和 CT0 cookie
- 可访问 Twitter 的 HTTP 代理

### 本地运行

```bash
# 1. 创建 .env 文件
cat > .env << EOF
AUTH_TOKEN=你的auth_token
CT0=你的ct0
HTTP_PROXY=http://127.0.0.1:1081
HTTPS_PROXY=http://127.0.0.1:1081
EOF

# 2. 启动应用
python app.py

# 3. 访问 http://127.0.0.1:5210
```

### Windows 快捷启动

```bash
start.bat
```

### Docker 代理部署

xray-core 代理用于访问 Twitter API，使用 Docker 部署在 NAS 或本地服务器上。

```bash
# 1. 从 VLESS 订阅生成代理配置
python setup_proxy.py

# 2. 启动 Docker 容器
docker compose up -d

# 3. 验证代理是否工作
curl -s --proxy http://127.0.0.1:1081 https://api.twitter.com

# 查看代理日志
docker logs xray-proxy -f

# 停止代理
docker compose down
```

**docker-compose.yml:**
```yaml
services:
  xray:
    image: teddysun/xray:latest
    container_name: xray-proxy
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./xray_config.json:/etc/xray/config.json
    command: ["xray", "run", "-c", "/etc/xray/config.json"]
```

**代理端口:**
- HTTP 代理: `127.0.0.1:1081`
- SOCKS5 代理: `127.0.0.1:1080`

### NAS 完整部署

一键部署到飞牛 NAS（需要先配置好 SSH 和 Docker）：

```bash
# 1. 部署 xray 代理到 NAS
python deploy_to_nas.py

# 2. 部署应用到 NAS
python deploy_app.py

# 3. 上传本地媒体文件到 NAS
python upload_media.py
```

部署后应用运行在 `http://NAS_IP:5210`，通过 systemd 管理服务，开机自启。

## 配置说明

在 `app.py` 的 CONFIG 字典中可修改：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| host | 0.0.0.0 | 监听地址 |
| port | 5210 | 监听端口 |
| media_base | ./media | 媒体存储目录 |
| proxy | http://127.0.0.1:1081 | HTTP 代理地址 |
| fetch_interval | 1800 | 自动抓取间隔（秒） |
| default_count | 100 | 默认抓取推文数量 |

## API 端点

### 时间线

```
GET /api/timeline
  ?page=1           # 页码
  &per_page=30      # 每页数量
  &username=xxx     # 按用户筛选
  &media_only=1     # 仅含媒体的推文
```

### 用户

```
GET  /api/user/{username}          # 获取用户信息
GET  /api/user/{username}/tweets   # 获取用户推文
POST /api/refresh/{username}       # 手动刷新用户推文
POST /api/refresh-all              # 刷新所有关注用户
```

### 关注管理

```
GET    /api/follows               # 获取关注列表
POST   /api/follows               # 添加关注 (body: {username, count})
DELETE /api/follows/{username}     # 移除关注
```

### 其他

```
GET    /api/stats                  # 获取统计数据
GET    /api/search?q=keyword       # 搜索推文
GET    /api/media/{path}           # 获取本地媒体文件
DELETE /api/tweets/{tweet_id}      # 删除推文（记录到 deleted_tweets）
GET    /api/cookies                # 获取 cookie 状态
POST   /api/cookies                # 更新 cookie
```

## 文件结构

```
offline-twitter/
├── app.py                    # Flask 后端主程序
├── .env                      # 环境变量配置
├── tweets.db                 # SQLite 数据库（自动创建）
├── media/                    # 下载的媒体文件
│
├── static/                   # 前端文件
│   ├── index.html            #   主页面
│   ├── style.css             #   暗色主题样式
│   └── app.js                #   前端逻辑
│
├── scripts/
│   ├── db/                   # 数据库维护脚本
│   │   ├── import_existing.py    # 导入已有媒体文件
│   │   └── update_metadata.py    # 更新推文元数据
│   ├── deploy/               # 部署脚本
│   │   ├── deploy_app.py         # 部署应用到 NAS
│   │   ├── deploy_to_nas.py      # 部署代理到 NAS
│   │   ├── upload_media.py       # 上传媒体到 NAS
│   │   ├── setup_proxy.py        # 生成代理配置
│   │   └── nas_setup.sh          # NAS 初始化脚本
│   └── test/                 # 测试脚本
│       ├── test_avatar.py
│       ├── test_profile.py
│       ├── test_profile_debug.py
│       └── test_profile_debug2.py
│
├── docs/                     # 文档
│   └── overview.md               # 项目概述
│
├── start.bat                 # Windows 启动脚本
├── start.sh                  # Linux 启动脚本
├── docker-compose.yml        # Docker 代理配置
└── xray_config.json          # xray 代理配置
```

## 数据库表结构

| 表名 | 说明 |
|------|------|
| users | 用户信息（用户名、头像、简介、粉丝数等） |
| tweets | 推文内容（文本、时间、互动数据） |
| media | 媒体文件（图片/视频 URL、本地路径） |
| follow_list | 关注列表 |
| deleted_tweets | 已删除推文记录（防止重新下载） |

## 自动更新 Query ID

应用启动时会自动从 Twitter 网页获取最新的 GraphQL Query ID，确保 API 调用不会因 Twitter 更新而失效。每30分钟自动刷新一次。

## Docker 代理详细配置

### 手动生成配置

如果需要手动配置代理，可以编辑 `xray_config.json`：

```json
{
  "inbounds": [
    {
      "tag": "http",
      "port": 1081,
      "listen": "127.0.0.1",
      "protocol": "http"
    },
    {
      "tag": "socks",
      "port": 1080,
      "listen": "127.0.0.1",
      "protocol": "socks",
      "settings": { "auth": "noauth", "udp": true }
    }
  ],
  "outbounds": [
    {
      "tag": "proxy",
      "protocol": "vless",
      "settings": {
        "vnext": [{
          "address": "你的服务器地址",
          "port": 443,
          "users": [{ "id": "你的UUID", "encryption": "none" }]
        }]
      },
      "streamSettings": {
        "network": "ws",
        "security": "tls",
        "wsSettings": { "path": "/你的路径" }
      }
    }
  ]
}
```

### 订阅转换

`setup_proxy.py` 支持从 v2rayNG 格式的订阅链接自动解析 VLESS 节点：

```bash
# 自动选择日本节点，生成配置
python setup_proxy.py

# 生成的配置保存到 xray_config.json
```

### Docker 常用命令

```bash
# 查看容器状态
docker ps | grep xray-proxy

# 查看日志
docker logs xray-proxy --tail 50

# 重启容器
docker compose restart

# 更新镜像
docker compose pull && docker compose up -d

# 进入容器调试
docker exec -it xray-proxy sh
```

### 网络架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Offline    │────▶│  xray-proxy  │────▶│  Twitter/X  │
│  Twitter    │     │  (Docker)    │     │  API        │
│  :5210      │     │  :1081       │     │             │
└─────────────┘     └──────────────┘     └─────────────┘
```

## 许可证

MIT License
