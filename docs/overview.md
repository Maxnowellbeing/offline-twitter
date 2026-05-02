# Offline Twitter Web App

一个模仿推特界面的离线网页应用，本地运行，定时抓取指定博主的推文、图片和视频。

## 功能

- **仿推特UI**：暗色主题，时间线流、推文卡片、图片/视频展示
- **关注管理**：添加/移除关注的博主，自动抓取推文
- **媒体库**：按图片/视频筛选浏览所有媒体
- **搜索**：全文搜索推文内容
- **用户主页**：查看单个博主的推文和个人信息
- **Lightbox**：点击图片/视频全屏查看
- **定时抓取**：后台自动定时刷新所有关注博主的新内容
- **代理支持**：通过 Clash 代理访问 Twitter

## 技术栈

- 后端：Python Flask + SQLite
- 前端：纯 HTML/CSS/JS
- 抓取：Twitter GraphQL API（通过代理）
- 媒体存储：F:\V

## 使用方法

### 启动服务器

```bash
# 方式1：使用启动脚本
start.bat

# 方式2：手动启动
cd offline-twitter
set AUTH_TOKEN=your_token
set CT0=your_ct0
set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897
python app.py
```

访问 http://127.0.0.1:5210

### 首次导入

```bash
# 导入已有的本地媒体文件
python import_existing.py

# 更新推文元数据（文本、日期等）
python update_metadata.py
```

### API 端点

| 端点 | 说明 |
|------|------|
| GET /api/timeline | 获取时间线（支持 ?username=&media_only=&per_page=） |
| GET /api/user/{username} | 获取用户信息 |
| GET /api/user/{username}/tweets | 获取用户推文 |
| GET /api/media/{path} | 获取本地媒体文件 |
| GET /api/follows | 获取关注列表 |
| POST /api/follows | 添加关注（body: {username, count}） |
| DELETE /api/follows/{username} | 移除关注 |
| POST /api/refresh/{username} | 手动刷新用户推文 |
| POST /api/refresh-all | 刷新全部 |
| GET /api/stats | 获取统计数据 |
| GET /api/search?q=keyword | 搜索推文 |

## 文件结构

```
offline-twitter/
├── app.py              # Flask 后端主程序
├── import_existing.py  # 导入已有媒体脚本
├── update_metadata.py  # 更新推文元数据脚本
├── start.bat           # Windows 启动脚本
├── tweets.db           # SQLite 数据库（自动创建）
└── static/
    ├── index.html      # 主页面
    ├── style.css       # 推特风格暗色主题
    └── app.js          # 前端逻辑
```

## 配置

在 `app.py` 中的 CONFIG 字典可修改：

- `port`: 服务端口（默认 5210）
- `media_base`: 媒体存储目录（默认 F:\V）
- `proxy`: 代理地址（默认 http://127.0.0.1:1081）
- `fetch_interval`: 自动抓取间隔秒数（默认 1800 = 30分钟）
