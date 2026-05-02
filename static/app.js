/**
 * Offline Blog — Premium Dark
 */
const API = '';
let currentPage = 'home';
let currentUser = null;
let mediaFilter = 'all';

// ===== Navigation =====
function navigateTo(page, data) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-a').forEach(n => n.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    const navItem = document.querySelector(`.nav-a[data-page="${page}"]`);
    if (navItem) navItem.classList.add('active');

    switch (page) {
        case 'home': loadTimeline(); break;
        case 'explore': renderSidebar('explore-sidebar'); break;
        case 'media': loadMediaGallery(); break;
        case 'follows': loadFollowList(); renderSidebar('follows-sidebar'); break;
        case 'favorites': loadFavorites(); break;
        case 'user': currentUser = data; loadUserProfile(data); break;
    }
}

// ===== Data Helpers =====
async function loadStats() {
    try { const r = await fetch(`${API}/api/stats`); return await r.json(); }
    catch { return {}; }
}
async function loadFollowsData() {
    try { const r = await fetch(`${API}/api/follows`); return (await r.json()).follows || []; }
    catch { return []; }
}

// ===== Sidebar =====
function renderSidebar(targetId) {
    const el = document.getElementById(targetId);
    if (!el || el.innerHTML) return;
    loadStats().then(s => { el.innerHTML = renderStatsCard(s); });
}

function renderStatsCard(s) {
    return `<div class="sb-card"><h4>数据概览</h4>
        <div class="stat-grid">
            <div class="stat-box"><div class="num">${fmtC(s.total_tweets||0)}</div><div class="label">推文</div></div>
            <div class="stat-box"><div class="num">${fmtC(s.total_media||0)}</div><div class="label">媒体</div></div>
            <div class="stat-box"><div class="num">${fmtC(s.followed_users||0)}</div><div class="label">关注</div></div>
            <div class="stat-box"><div class="num">${fmtC(s.photo_count||0)}</div><div class="label">图片</div></div>
            <div class="stat-box"><div class="num">${fmtC(s.video_count||0)}</div><div class="label">视频</div></div>
            <div class="stat-box"><div class="num">${fmtC(s.total_users||0)}</div><div class="label">用户</div></div>
        </div></div>`;
}

function renderFollowsCard(follows) {
    if (!follows.length) return '';
    const items = follows.slice(0, 8).map(f => {
        const av = f.avatar_url
            ? `<div class="sb-fav"><img src="${f.avatar_url}" onerror="this.outerHTML=avPh('${esc(f.display_name||f.username)}')"></div>`
            : `<div class="sb-fav">${avPh(f.display_name||f.username)}</div>`;
        return `<div class="sb-follow-item" onclick="navigateTo('user','${f.username}')">
            ${av}<div class="sb-finfo"><div class="sb-fname">${esc(f.display_name||f.username)}</div><div class="sb-fhandle">@${f.username}</div></div>
            <div class="sb-factions" onclick="event.stopPropagation()">
                <button class="sb-btn" onclick="refreshUser('${f.username}')">刷新</button>
                <button class="sb-btn danger" onclick="removeFollow('${f.username}')">移除</button>
            </div>
        </div>`;
    }).join('');
    return `<div class="sb-card"><h4>关注列表</h4><div class="sb-follow">${items}</div></div>`;
}

// ===== Timeline =====
async function loadTimeline() {
    const el = document.getElementById('timeline');
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/timeline?per_page=30`);
        const d = await r.json();
        if (d.tweets?.length) {
            // Check favorites status
            const tweetIds = d.tweets.map(t => t.id).join(',');
            const favR = await fetch(`${API}/api/favorites/check?tweet_ids=${tweetIds}`);
            const favD = await favR.json();
            d.tweets.forEach(t => { t.is_favorited = !!favD.favorites?.[t.id]; });
            el.innerHTML = d.tweets.map(renderPostCard).join('');
        } else {
            el.innerHTML = '<div class="empty"><h3>还没有内容</h3><p>点击右上角 "+ 关注" 添加博主</p></div>';
        }
    } catch (e) {
        el.innerHTML = `<div class="empty"><h3>加载失败</h3><p>${e.message}</p></div>`;
    }
    const sb = document.getElementById('home-sidebar');
    const [stats, follows] = await Promise.all([loadStats(), loadFollowsData()]);
    sb.innerHTML = renderStatsCard(stats) + renderFollowsCard(follows);
}

// ===== Render Post Card =====
function renderPostCard(t) {
    const name = esc(t.display_name || t.username);
    const handle = `@${t.username}`;
    const text = fmtText(t.text || '');
    const time = fmtTime(t.created_at);

    const avHtml = t.avatar_url
        ? `<div class="post-avatar"><img src="${t.avatar_url}" onerror="this.outerHTML=avPh('${esc(name)}')"></div>`
        : `<div class="post-avatar">${avPh(name)}</div>`;

    const coverHtml = t.media?.length ? renderCover(t.media) : '';
    const isFav = t.is_favorited ? ' active' : '';

    return `<article class="post-card" onclick="navigateTo('user','${t.username}')">
        ${coverHtml}
        <div class="post-body">
            <div class="post-meta">
                ${avHtml}
                <div>
                    <span class="post-author">${name}</span>
                    <span class="post-dot">·</span>
                    <span class="post-handle">${handle}</span>
                </div>
                <span class="post-time">${time}</span>
            </div>
            ${text ? `<div class="post-text">${text}</div>` : ''}
            <div class="post-footer">
                <button class="btn-fav${isFav}" onclick="event.stopPropagation();toggleFavorite('${t.id}',this)" title="收藏">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
                </button>
                <button class="btn-del" onclick="event.stopPropagation();deleteTweet('${t.id}',this)" title="删除推文">&times;</button>
            </div>
        </div>
    </article>`;
}

// ===== Render Cover =====
function renderCover(list) {
    const n = list.length;
    const gc = n === 1 ? 'g1' : n === 2 ? 'g2' : n >= 4 ? 'g4' : 'g3';
    const items = list.slice(0, 4).map(m => {
        if (!m.local_path) return '';
        const ep = m.local_path.split('/').map(s => encodeURIComponent(s)).join('/');
        const src = `${API}/api/media/${ep}`;
        if (m.media_type === 'video') {
            return `<div class="cover-item" data-src="${src}" data-type="video" onclick="event.stopPropagation();openLightbox('${src}','video')">
                <video src="${src}" preload="metadata" muted></video><span class="vbadge">${fmtDur(m.duration_ms) || ''}</span></div>`;
        }
        return `<div class="cover-item" data-src="${src}" data-type="image" onclick="event.stopPropagation();openLightbox('${src}','image')">
            <img src="${src}" loading="lazy"></div>`;
    }).join('');
    return `<div class="post-cover-grid ${gc}">${items}</div>`;
}

// ===== User Profile =====
async function loadUserProfile(username) {
    try {
        const r = await fetch(`${API}/api/user/${username}`);
        const u = await r.json();

        const avHtml = u.avatar_url
            ? `<div class="profile-av"><img src="${u.avatar_url}" onerror="this.outerHTML=avPh('${esc(u.display_name||u.username)}')"></div>`
            : `<div class="profile-av">${avPh(u.display_name||u.username)}</div>`;

        const bannerHtml = u.banner_url
            ? `<div class="profile-banner"><img src="${u.banner_url}"></div>`
            : `<div class="profile-banner"></div>`;

        document.getElementById('user-sidebar').innerHTML = `<div class="sb-card profile-card">
            ${bannerHtml}
            <div class="profile-inner">
                <div class="profile-av-wrap">${avHtml}</div>
                <div class="profile-name">${esc(u.display_name||u.username)}</div>
                <div class="profile-handle">@${u.username}</div>
                ${u.bio ? `<div class="profile-bio">${esc(u.bio)}</div>` : ''}
                <div class="profile-stats-row">
                    <span><strong>${fmtC(u.following_count)}</strong> 关注</span>
                    <span><strong>${fmtC(u.followers_count)}</strong> 粉丝</span>
                </div>
                <button class="profile-btn" onclick="refreshUser('${u.username}')">刷新推文</button>
            </div>
        </div>` + renderStatsCard(await loadStats());
    } catch (e) { console.error(e); }

    const tc = document.getElementById('user-posts');
    tc.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/user/${username}/tweets?per_page=50`);
        const d = await r.json();
        if (d.tweets?.length) {
            // Check favorites status
            const tweetIds = d.tweets.map(t => t.id).join(',');
            const favR = await fetch(`${API}/api/favorites/check?tweet_ids=${tweetIds}`);
            const favD = await favR.json();
            d.tweets.forEach(t => { t.is_favorited = !!favD.favorites?.[t.id]; });
            tc.innerHTML = d.tweets.map(renderPostCard).join('');
        } else {
            tc.innerHTML = '<div class="empty"><h3>暂无推文</h3></div>';
        }
    } catch { tc.innerHTML = '<div class="empty"><h3>加载失败</h3></div>'; }
}

// ===== Media Gallery =====
async function loadMediaGallery() {
    const el = document.getElementById('media-gallery');
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/timeline?per_page=100&media_only=1`);
        const d = await r.json();
        let all = [];
        d.tweets.forEach(t => t.media?.forEach(m => all.push({...m})));
        if (mediaFilter !== 'all') all = all.filter(m => m.media_type === mediaFilter);
        el.innerHTML = all.length
            ? all.map(m => {
                if (!m.local_path) return '';
                const ep = m.local_path.split('/').map(s => encodeURIComponent(s)).join('/');
                const src = `${API}/api/media/${ep}`;
                return m.media_type === 'video'
                    ? `<div class="m-item" data-src="${src}" data-type="video" onclick="openLightbox('${src}','video')"><video src="${src}" preload="metadata" muted></video><span class="vbadge">${fmtDur(m.duration_ms) || '▶'}</span></div>`
                    : `<div class="m-item" data-src="${src}" data-type="image" onclick="openLightbox('${src}','image')"><img src="${src}" loading="lazy"></div>`;
            }).join('')
            : '<div class="empty"><h3>暂无媒体</h3></div>';
    } catch { el.innerHTML = '<div class="empty"><h3>加载失败</h3></div>'; }

    document.getElementById('media-sidebar').innerHTML = renderStatsCard(await loadStats());
}

function filterMedia(type, btn) {
    mediaFilter = type;
    document.querySelectorAll('.ftab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadMediaGallery();
}

// ===== Follow List =====
async function loadFollowList() {
    const el = document.getElementById('follow-list');
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/follows`);
        const d = await r.json();
        el.innerHTML = d.follows?.length
            ? `<div class="follow-grid">${d.follows.map(f => {
                const av = f.avatar_url
                    ? `<div class="fav"><img src="${f.avatar_url}" onerror="this.outerHTML=avPh('${esc(f.display_name||f.username)}')"></div>`
                    : `<div class="fav">${avPh(f.display_name||f.username)}</div>`;
                return `<div class="follow-card" onclick="navigateTo('user','${f.username}')">
                    ${av}
                    <div class="fname">${esc(f.display_name||f.username)}</div>
                    <div class="fhandle">@${f.username}</div>
                    ${f.bio ? `<div class="fbio">${esc(f.bio)}</div>` : ''}
                    <div class="factions" onclick="event.stopPropagation()">
                        <button class="sb-btn" onclick="refreshUser('${f.username}')">刷新</button>
                        <button class="sb-btn danger" onclick="removeFollow('${f.username}')">移除</button>
                    </div>
                </div>`;
            }).join('')}</div>`
            : '<div class="empty"><h3>还没有关注博主</h3><p>点击右上角 "+ 关注" 开始</p></div>';
    } catch { el.innerHTML = '<div class="empty"><h3>加载失败</h3></div>'; }
}

// ===== Search =====
async function searchTweets() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) return;
    const el = document.getElementById('search-results');
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
        const d = await r.json();
        if (d.tweets?.length) {
            // Check favorites status
            const tweetIds = d.tweets.map(t => t.id).join(',');
            const favR = await fetch(`${API}/api/favorites/check?tweet_ids=${tweetIds}`);
            const favD = await favR.json();
            d.tweets.forEach(t => { t.is_favorited = !!favD.favorites?.[t.id]; });
            el.innerHTML = d.tweets.map(renderPostCard).join('');
        } else {
            el.innerHTML = '<div class="empty"><h3>未找到结果</h3></div>';
        }
    } catch { el.innerHTML = '<div class="empty"><h3>搜索失败</h3></div>'; }
}

// ===== Actions =====
function showAddFollow() {
    document.getElementById('modal-follow').style.display = 'flex';
    document.getElementById('follow-username').focus();
}
function closeModal() { document.getElementById('modal-follow').style.display = 'none'; }

async function addFollow() {
    const raw = document.getElementById('follow-username').value.trim();
    const username = raw.startsWith('@') ? raw.slice(1) : raw;
    const count = parseInt(document.getElementById('follow-count').value) || 200;
    if (!username) return;
    closeModal();
    await fetch(`${API}/api/follows`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, count }) });
    setTimeout(() => { if (currentPage === 'follows') loadFollowList(); }, 3000);
}

async function removeFollow(u) {
    await fetch(`${API}/api/follows/${u}`, { method: 'DELETE' });
    if (currentPage === 'follows') loadFollowList();
}

async function refreshUser(u) {
    await fetch(`${API}/api/refresh/${u}`, { method: 'POST' });
    setTimeout(() => { if (currentPage === 'user' && currentUser === u) loadUserProfile(u); }, 5000);
}

async function refreshAll() {
    await fetch(`${API}/api/refresh-all`, { method: 'POST' });
    setTimeout(() => { if (currentPage === 'home') loadTimeline(); }, 5000);
}

// ===== Favorites =====
async function toggleFavorite(tweetId, btn) {
    const isActive = btn.classList.contains('active');
    if (isActive) {
        await fetch(`${API}/api/favorites/${tweetId}`, { method: 'DELETE' });
        btn.classList.remove('active');
    } else {
        await fetch(`${API}/api/favorites/${tweetId}`, { method: 'POST' });
        btn.classList.add('active');
        btn.classList.remove('animate');
        void btn.offsetWidth;
        btn.classList.add('animate');
    }
}

async function loadFavorites() {
    const el = document.getElementById('favorites-list');
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/favorites?per_page=50`);
        const d = await r.json();
        el.innerHTML = d.tweets?.length
            ? d.tweets.map(t => { t.is_favorited = true; return renderPostCard(t); }).join('')
            : '<div class="empty"><h3>还没有收藏</h3><p>点击推文下方的爱心图标收藏</p></div>';
    } catch { el.innerHTML = '<div class="empty"><h3>加载失败</h3></div>'; }

    document.getElementById('favorites-sidebar').innerHTML = renderStatsCard(await loadStats());
}

// ===== Lightbox =====
let lbList = [];   // [{src, type}, ...]
let lbIndex = 0;

function openLightbox(src, type) {
    // Try to find the media list context from the clicked element
    lbList = [];
    lbIndex = 0;

    // Collect all visible media items on the current page
    const page = document.querySelector('.page.active');
    if (page) {
        // Timeline / User posts / Search: collect from .cover-item and .m-item
        const items = page.querySelectorAll('.cover-item[data-src], .m-item[data-src]');
        items.forEach(el => {
            lbList.push({ src: el.dataset.src, type: el.dataset.type || 'image' });
        });
    }

    // If no context found, just use the single item
    if (!lbList.length) {
        lbList = [{ src, type }];
    }

    // Find the index of the clicked item
    lbIndex = lbList.findIndex(m => m.src === src);
    if (lbIndex < 0) lbIndex = 0;

    renderLbItem();
    document.getElementById('lightbox').style.display = 'flex';
}

function renderLbItem() {
    const m = lbList[lbIndex];
    if (!m) return;
    document.getElementById('lightbox-content').innerHTML = m.type === 'video'
        ? `<video src="${m.src}" controls autoplay style="max-width:90vw;max-height:88vh"></video>`
        : `<img src="${m.src}">`;

    // Show/hide arrows
    const prev = document.querySelector('.lb-prev');
    const next = document.querySelector('.lb-next');
    const counter = document.getElementById('lb-counter');
    if (lbList.length <= 1) {
        prev.style.display = 'none';
        next.style.display = 'none';
        counter.style.display = 'none';
    } else {
        prev.style.display = lbIndex > 0 ? '' : 'none';
        next.style.display = lbIndex < lbList.length - 1 ? '' : 'none';
        counter.style.display = '';
        counter.textContent = `${lbIndex + 1} / ${lbList.length}`;
    }
}

function lbNav(dir) {
    const ni = lbIndex + dir;
    if (ni < 0 || ni >= lbList.length) return;
    const v = document.querySelector('#lightbox-content video');
    if (v) v.pause();
    lbIndex = ni;
    renderLbItem();
}

function closeLightbox(e) {
    if (e && e.target !== document.getElementById('lightbox')) return;
    // Pause video if playing
    const v = document.querySelector('#lightbox-content video');
    if (v) v.pause();
    document.getElementById('lightbox-content').innerHTML = '';
    document.getElementById('lightbox').style.display = 'none';
}
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') lbNav(-1);
    if (e.key === 'ArrowRight') lbNav(1);
});

// ===== Helpers =====
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function avPh(name) {
    const c = ['#818cf8','#22d3ee','#f472b6','#fbbf24','#a78bfa','#34d399'];
    return `<div style="background:linear-gradient(135deg,${c[name.charCodeAt(0)%c.length]},${c[(name.charCodeAt(0)+2)%c.length]}55);width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:inherit">${(name||'?')[0].toUpperCase()}</div>`;
}

function fmtText(text) {
    let r = esc(text);
    r = r.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank">$1</a>');
    r = r.replace(/@(\w+)/g, '<span class="mention">@$1</span>');
    r = r.replace(/#(\w+)/g, '<span class="hashtag">#$1</span>');
    return r;
}

function fmtTime(s) {
    if (!s) return '';
    try {
        const d = new Date(s), now = new Date(), diff = (now - d) / 1000;
        if (diff < 60) return '刚刚';
        if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
        if (diff < 604800) return `${Math.floor(diff / 86400)}天前`;
        return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    } catch { return s; }
}

function fmtC(n) {
    if (!n || n === 0) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
}

function fmtDur(ms) {
    if (!ms || ms <= 0) return '';
    const s = Math.round(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}:${String(sec).padStart(2, '0')}` : `0:${String(sec).padStart(2, '0')}`;
}

// ===== Delete Tweet =====
async function deleteTweet(id, btn) {
    if (!confirm('确定删除这条推文？本地媒体文件也会被删除。')) return;
    const card = btn.closest('.post-card');
    if (card) card.style.opacity = '0.4';
    await fetch(`${API}/api/tweets/${id}`, { method: 'DELETE' });
    if (card) card.remove();
}

// ===== Cookie Management =====
async function showCookies() {
    document.getElementById('modal-cookies').style.display = 'flex';
    const statusEl = document.getElementById('cookie-status');
    statusEl.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/cookies`);
        const d = await r.json();
        statusEl.innerHTML = `
            <div class="cookie-info">
                <div class="cookie-row"><span class="cookie-key">AUTH_TOKEN:</span> ${d.has_auth_token ? `<code>${esc(d.auth_token_preview)}</code>` : '<span class="tag-warn">未设置</span>'}</div>
                <div class="cookie-row"><span class="cookie-key">CT0:</span> ${d.has_ct0 ? `<code>${esc(d.ct0_preview)}</code>` : '<span class="tag-warn">未设置</span>'}</div>
                <div class="cookie-row"><span class="cookie-key">代理:</span> <code>${esc(d.proxy || '未设置')}</code></div>
            </div>`;
        document.getElementById('cookie-proxy').value = d.proxy || '';
    } catch {
        statusEl.innerHTML = '<div class="tag-warn">加载失败</div>';
    }
}
function closeCookies() {
    document.getElementById('modal-cookies').style.display = 'none';
}
async function saveCookies() {
    const body = {};
    const auth = document.getElementById('cookie-auth').value;
    const ct0 = document.getElementById('cookie-ct0').value;
    const proxy = document.getElementById('cookie-proxy').value;
    if (auth) body.auth_token = auth;
    if (ct0) body.ct0 = ct0;
    if (proxy) body.proxy = proxy;
    if (!Object.keys(body).length) return;
    await fetch(`${API}/api/cookies`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    document.getElementById('cookie-auth').value = '';
    document.getElementById('cookie-ct0').value = '';
    closeCookies();
}

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => { navigateTo('home'); });
