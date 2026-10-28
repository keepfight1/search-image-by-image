<template>
  <div class="shell">
    <header class="topbar">
      <strong class="brand">🐾 寻猫线索</strong>
      <nav><button v-for="tab in visibleTabs" :key="tab.id" :class="{ active: page === tab.id }" @click="navigate(tab.id)">{{ tab.label }}</button></nav>
      <button class="link" @click="token ? logout() : (authOpen = true)">{{ token ? `${username} · 退出` : '登录 / 注册' }}</button>
    </header>
    <main>
      <section class="hero"><p class="eyebrow">让每一条目击都有机会被看见</p><h1>一起帮猫找到回家的路</h1><p>发现无主猫时发布目击信息；丢猫用户上传自家猫照片，在发现线索中进行检索。候选需要由双方进一步核实。</p><div class="actions"><button class="primary" @click="choose('lost')">我的猫走失了</button><button class="secondary" @click="choose('sighting')">我发现了一只猫</button></div></section>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>

      <section v-if="page === 'publish'" class="content">
        <div class="heading"><span>{{ editingReport ? '编辑线索' : '发布发现线索' }}</span><h2>{{ editingReport ? '编辑已发布的发现线索' : '发布发现的未知主人猫咪' }}</h2><p>此通道只发布发现猫信息。发现地点和时间必须填写，品种、毛色不确定时可以留空。</p></div>
        <form class="panel" @submit.prevent="publish">
          <div class="grid">
            <label>发现城市 *<input v-model.trim="form.event_city" required maxlength="100" placeholder="例如：上海" /></label>
            <label>发现区县 *<input v-model.trim="form.event_district" required maxlength="100" placeholder="例如：浦东新区" /></label>
            <label>发现时间 *<input v-model="form.event_time" required type="datetime-local" /></label>
            <label>联系电话 *<input v-model.trim="form.contact" required type="tel" inputmode="tel" maxlength="30" placeholder="例如：13800138000" /></label>
            <label>毛色<input v-model.trim="form.desc.coat_color" maxlength="50" placeholder="例如：橘白；不确定可留空" /></label>
            <label>花纹<input v-model.trim="form.desc.pattern" maxlength="50" placeholder="例如：虎斑" /></label>
            <label>品种<input v-model.trim="form.desc.breed" maxlength="100" placeholder="不确定可留空" /></label>
            <label>体型<select v-model="form.desc.size"><option value="">不确定</option><option>小</option><option>中</option><option>大</option></select></label>
          </div>
          <div class="location"><div><strong>发现地点坐标（选填）</strong><p>只有你仍在发现猫的位置附近时，才使用当前定位。</p></div><button type="button" class="secondary small" @click="useLocation">使用当前位置</button><span v-if="form.event_lat !== null">已定位</span></div>
          <label class="upload">猫的照片 * <small>1–5 张 JPG/PNG，建议包含正脸、侧面和全身。</small><input type="file" accept="image/jpeg,image/png" multiple @change="selectFiles" /></label>
          <div v-if="existingImages.length" class="previews"><div v-for="(src, i) in existingImages" :key="src"><img :src="src" :alt="`已上传照片 ${i + 1}`" /><button type="button" @click="existingImages.splice(i, 1)">×</button></div></div>
          <div v-if="previews.length" class="previews"><div v-for="(src, i) in previews" :key="src"><img :src="src" :alt="`待上传照片 ${i + 1}`" /><button type="button" @click="removeFile(i)">×</button></div></div>
          <p class="tip">浏览信息时，其他用户点击“联系发布者”即可看到你填写的电话号码。</p>
          <button class="primary submit" :disabled="busy">{{ busy ? '正在保存…' : editingReport ? '保存修改' : '发布线索' }}</button>
        </form>
      </section>

      <section v-else-if="page === 'match'" class="content">
        <div class="heading"><span>走失猫以图搜图</span><h2>为走失猫查找发现线索</h2><p>上传自家走失猫的照片，在平台已发布的发现猫线索中检索。地点和时间均为选填，留空即不限制。</p></div>
        <form class="panel" @submit.prevent="runImageMatch">
          <div class="grid">
            <label>可能走失城市（选填）<input v-model.trim="matchForm.city" maxlength="100" placeholder="留空搜索全部城市" /></label>
            <label>可能走失区县（选填）<input v-model.trim="matchForm.district" maxlength="100" placeholder="留空搜索全部区县" /></label>
            <label>发现线索开始日期（选填）<input v-model="matchForm.since" type="date" /></label>
            <label>发现线索结束日期（选填）<input v-model="matchForm.until" type="date" /></label>
            <label>毛色<select v-model="matchForm.coat_color"><option value="">全部毛色</option><option v-for="color in coatOptions" :key="color">{{ color }}</option></select></label>
            <label>花纹<select v-model="matchForm.pattern"><option value="">全部花纹</option><option v-for="pattern in patternOptions" :key="pattern">{{ pattern }}</option></select></label>
            <label>品种<input v-model.trim="matchForm.breed" maxlength="100" placeholder="留空不限品种" /></label>
            <label>体型<select v-model="matchForm.size"><option value="">全部体型</option><option>小</option><option>中</option><option>大</option></select></label>
            <label>最多显示<select v-model.number="matchForm.top_k"><option :value="10">10 条</option><option :value="20">20 条</option><option :value="50">50 条</option></select></label>
          </div>
          <label class="upload match-upload">走失猫照片 * <small>1–5 张 JPG/PNG，每张不超过 5MB。正脸、侧面和全身照可一起上传。</small><input type="file" accept="image/jpeg,image/png" multiple @change="selectMatchFiles" /></label>
          <div v-if="matchPreviews.length" class="previews"><div v-for="(src, i) in matchPreviews" :key="src"><img :src="src" :alt="`查询照片 ${i + 1}`" /><button type="button" @click="removeMatchFile(i)">×</button></div></div>
          <p class="tip">筛选条件用于限制候选范围；相似分只是排序依据。</p>
          <button type="button" class="secondary match-reset" @click="resetMatchFilters">清空筛选条件</button>
          <button class="primary submit" :disabled="busy">{{ busy ? '正在匹配…' : '上传照片并开始匹配' }}</button>
        </form>
        <details v-if="token && matchableItems.length" class="saved-match"><summary>或者使用以前发布的走失线索匹配</summary><div class="panel match-panel"><label>历史走失线索<select v-model="selectedMatchKey" @change="matchesShown = false"><option value="">请选择一条走失线索</option><option v-for="item in matchableItems" :key="`${item.type}-${item.id}`" :value="`${item.type}:${item.id}`">走失 · {{ item.desc.coat_color || '毛色未知' }}</option></select></label><button class="primary" :disabled="busy || !selectedMatchKey" @click="runSelectedMatch">开始匹配</button></div></details>
        <section v-if="matchesShown" class="results">
          <div class="heading"><span>检索结果</span><h2>可能相关的线索</h2><p>每只猫的已索引照片都会参与比对，结果按线索合并展示。图像相似分用于排序，不代表认领概率。当前范围：{{ searchScope === 'custom' ? '所选筛选条件' : searchScope === 'all_cities' ? '全部城市' : '同城' }}。</p><button v-if="activeReport && searchScope !== 'all_cities'" class="secondary small" @click="expandMatches">扩大到全部城市</button></div>
          <div v-if="!matches.length" class="empty">暂时没有符合条件的候选；可放宽筛选条件后再试。</div>
          <div v-else class="result-grid"><article v-for="item in matches" :key="item.id" class="result"><img :src="item.image_url" alt="候选猫照片" /><div><h3>{{ item.desc.coat_color || '毛色未知' }}的猫</h3><p>{{ item.desc.pattern || '花纹未知' }} · {{ item.desc.breed || '品种未知' }}</p><p>图像相似分 {{ item.score.toFixed(3) }}</p><button class="secondary small" @click="openDetails(item, matchTargetType)">查看详细信息</button><button class="link" @click="flag(item, matchTargetType)">举报</button></div></article></div>
        </section>
      </section>

      <section v-else-if="page === 'browse'" class="content">
        <div class="heading"><span>全部信息</span><h2>浏览猫咪与寻猫线索</h2><p>默认显示全部走失与发现线索，可按条件筛选并查看完整资料。</p></div>
        <div class="browse-filters panel">
          <label>信息类型<select v-model="browseFilters.type"><option value="all">全部</option><option value="lost">走失猫</option><option value="sighting">发现猫</option></select></label>
          <label>城市<input v-model.trim="browseFilters.city" placeholder="全部城市" /></label>
          <label>区县<input v-model.trim="browseFilters.district" placeholder="全部区县" /></label>
          <label>毛色<select v-model="browseFilters.coat_color"><option value="">全部毛色</option><option v-for="color in coatOptions" :key="color">{{ color }}</option></select></label>
          <label>花纹<select v-model="browseFilters.pattern"><option value="">全部花纹</option><option v-for="pattern in patternOptions" :key="pattern">{{ pattern }}</option></select></label>
          <label>品种<input v-model.trim="browseFilters.breed" placeholder="品种关键词" /></label>
          <label>开始日期<input v-model="browseFilters.since" type="date" /></label>
          <label>结束日期<input v-model="browseFilters.until" type="date" /></label>
          <div class="filter-actions"><button class="primary small" @click="loadBrowse(0)">应用筛选</button><button class="secondary small" @click="resetBrowse">清空筛选</button></div>
        </div>
        <p class="browse-count">共 {{ browseTotal }} 条信息</p>
        <div v-if="!browseItems.length" class="empty">暂无符合条件的信息。</div>
        <div v-else class="result-grid">
          <article v-for="item in browseItems" :key="`${item.type}-${item.id}`" class="result">
            <img :src="item.images[0]" alt="猫照片" loading="lazy" />
            <div>
              <small>{{ item.type === 'lost' ? '走失猫' : '发现猫' }}</small>
              <h3>{{ item.desc.coat_color || '毛色未知' }}的猫</h3>
              <p>{{ item.desc.pattern || '花纹未知' }} · {{ item.desc.breed || '品种未知' }}</p>
              <button class="secondary small" @click="openDetails(item, item.type)">查看详细信息</button><button class="link" @click="flag(item, item.type)">举报</button>
            </div>
          </article>
        </div>
        <div v-if="browseTotal > browseLimit" class="pagination"><button class="secondary small" :disabled="browseOffset === 0" @click="loadBrowse(Math.max(0, browseOffset - browseLimit))">上一页</button><span>{{ browseOffset + 1 }}–{{ Math.min(browseOffset + browseLimit, browseTotal) }} / {{ browseTotal }}</span><button class="secondary small" :disabled="browseOffset + browseLimit >= browseTotal" @click="loadBrowse(browseOffset + browseLimit)">下一页</button></div>
      </section>

      <section v-else-if="page === 'mine'" class="content">
        <div class="heading"><span>我的线索</span><h2>管理已发布的信息</h2><p>可编辑照片和电话；猫已找回时请及时关闭。</p></div>
        <div v-if="!token" class="empty">登录后可查看你的发布。</div>
        <div v-else-if="!myItems.length" class="empty">你还没有发布记录。</div>
        <div v-else class="my-list">
          <article v-for="item in myItems" :key="item.id" class="my-item">
            <img :src="item.images[0]" alt="猫照片" />
            <div><strong>{{ item.type === 'lost' ? '走失' : '发现' }} · {{ item.desc.coat_color || '毛色未知' }}</strong><p>{{ item.status }}</p></div>
            <div class="my-actions"><button class="secondary small" @click="openDetails(item, item.type)">查看详细信息</button><button v-if="!isSample(item) && item.type === 'sighting' && item.status === 'active'" class="secondary small" @click="startEdit(item)">编辑/补图</button><button v-if="!isSample(item) && item.type === 'lost' && item.status === 'active'" class="secondary small" @click="viewMatches(item)">查看匹配</button><button v-if="!isSample(item) && item.status === 'active'" class="link" @click="closeReport(item)">标记已解决</button></div>
          </article>
        </div>
      </section>
      <section v-else-if="page === 'admin'" class="content">
        <div class="heading"><span>管理员</span><h2>线索管理</h2><p>可删除走失和发现线索；删除后会从浏览和以图搜图结果中移除。</p></div>
        <div class="admin-toolbar"><label>类型<select v-model="adminType"><option value="all">全部线索</option><option value="lost">走失猫</option><option value="sighting">发现猫</option></select></label><label>状态<select v-model="adminStatus"><option value="all">全部状态</option><option value="active">进行中</option><option value="deleted">已删除</option><option value="resolved">已解决</option><option value="hidden">已隐藏</option></select></label><button class="secondary small" @click="loadAdminReports">刷新</button></div>
        <div v-if="!filteredAdminPublications.length" class="empty">暂无符合条件的线索。</div>
        <article v-for="item in filteredAdminPublications" :key="`${item.type}-${item.id}`" class="my-item admin-item">
          <img :src="item.images[0]" alt="猫照片" loading="lazy" />
          <div><strong>{{ item.type === 'lost' ? '走失' : '发现' }} · {{ item.desc.coat_color || '毛色未知' }}</strong><p>{{ item.status }} · {{ item.id }}</p></div>
          <button class="secondary small" @click="openDetails(item, item.type)">查看详细信息</button><button v-if="item.status !== 'deleted'" class="secondary small delete-button" @click="deletePublication(item)">删除线索</button>
        </article>
        <div class="heading admin-reports-heading"><h2>用户举报</h2><p>审核举报并隐藏不适宜或虚假的线索。</p></div>
        <div v-if="!adminReports.length" class="empty">暂无举报。</div>
        <article v-for="item in adminReports" :key="item.id" class="message">
          <strong>{{ item.target_type === 'lost' ? '走失' : '目击' }}线索 {{ item.target_id }}</strong>
          <p>{{ item.reason }}</p><small>{{ item.created_at }} · {{ item.state }}</small>
          <div v-if="item.state === 'pending'"><button class="secondary small" @click="moderate(item, 'hide')">隐藏线索</button><button class="secondary small" @click="moderate(item, 'dismiss')">驳回举报</button></div>
        </article>
      </section>
    </main>
    <div v-if="authOpen" class="overlay" @click.self="authOpen = false"><form class="dialog" @submit.prevent="authenticate"><button type="button" class="close" @click="authOpen = false">×</button><span class="eyebrow">寻猫线索</span><h2>{{ registerMode ? '创建账号' : '登录账号' }}</h2><label>用户名<input v-model.trim="auth.username" required minlength="3" autocomplete="username" /></label><label>密码<input v-model="auth.password" type="password" required minlength="8" :autocomplete="registerMode ? 'new-password' : 'current-password'" /></label><button class="primary submit" :disabled="busy">{{ registerMode ? '注册并登录' : '登录' }}</button><button type="button" class="link" @click="registerMode = !registerMode">{{ registerMode ? '已有账号？登录' : '没有账号？注册' }}</button></form></div>
    <div v-if="detailItem" class="overlay" @click.self="detailItem = null">
      <div class="dialog detail-dialog">
        <button type="button" class="close" @click="detailItem = null">×</button>
        <span class="eyebrow">{{ detailItem.type === 'lost' ? '走失猫信息' : '发现猫信息' }}</span>
        <h2>{{ detailItem.desc.coat_color || '毛色未知' }}的猫</h2>
        <p v-if="detailLoading">正在加载详细信息…</p>
        <div class="detail-grid">
          <div><small>所在地区</small><strong>{{ detailItem.city || '未填写' }} {{ detailItem.district || '' }}</strong></div>
          <div><small>{{ detailItem.type === 'lost' ? '最后见到时间' : '发现时间' }}</small><strong>{{ detailItem.event_time || '未填写' }}</strong></div>
          <div><small>毛色</small><strong>{{ detailItem.desc.coat_color || '未知' }}</strong></div>
          <div><small>花纹</small><strong>{{ detailItem.desc.pattern || '未知' }}</strong></div>
          <div><small>品种</small><strong>{{ detailItem.desc.breed || '未知' }}</strong></div>
          <div><small>体型</small><strong>{{ detailItem.desc.size || '未知' }}</strong></div>
          <div><small>联系电话</small><strong>{{ detailItem.phone || '未填写' }}</strong></div>
          <div><small>参与比对照片</small><strong>{{ detailItem.searchable_image_count || detailItem.images.length }} 张</strong></div>
          <div v-if="detailItem.score !== null"><small>图像相似分</small><strong>{{ detailItem.score.toFixed(3) }}</strong></div>
        </div>
        <p v-if="detailItem.reasons.length">匹配依据：{{ detailItem.reasons.join(' · ') }}</p>
        <div class="dataset-photos"><img v-for="url in detailItem.images" :key="url" :src="url" alt="猫的照片" loading="lazy" /></div>
        <button class="secondary" @click="detailItem = null">关闭</button>
      </div>
    </div>
    <div v-if="reportTarget" class="overlay" @click.self="reportTarget = null"><form class="dialog" @submit.prevent="sendReport"><button type="button" class="close" @click="reportTarget = null">×</button><span class="eyebrow">内容举报</span><h2>举报这条线索</h2><p>请说明虚假、重复或不适宜内容的具体情况。</p><textarea v-model.trim="reportReason" required minlength="10" maxlength="500" rows="5"></textarea><button class="primary submit" :disabled="busy">提交举报</button></form></div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onUnmounted } from 'vue'
import axios from 'axios'

const tabs = [{ id: 'publish', label: '发布线索' }, { id: 'match', label: '匹配线索' }, { id: 'browse', label: '浏览信息' }, { id: 'mine', label: '我的发布' }, { id: 'admin', label: '管理员' }]
const page = ref('publish'), notice = ref(''), busy = ref(false)
const token = ref(localStorage.getItem('cat_token') || ''), username = ref(localStorage.getItem('cat_user') || '')
const role = ref(localStorage.getItem('cat_role') || 'user'), visibleTabs = computed(() => tabs.filter(tab => tab.id !== 'admin' || role.value === 'admin'))
const authOpen = ref(false), registerMode = ref(false), auth = reactive({ username: '', password: '' })
const form = reactive({ type: 'sighting', event_city: '', event_district: '', event_time: '', event_lat: null, event_lng: null, contact: '', desc: { coat_color: '', pattern: '', size: '', breed: '' } })
const files = ref([]), previews = ref([]), existingImages = ref([]), editingReport = ref(null), matches = ref([]), matchesShown = ref(false), matchTargetType = ref('sighting'), searchScope = ref('same_city'), activeReport = ref(null)
const matchForm = reactive({ type: 'lost', city: '', district: '', since: '', until: '', coat_color: '', pattern: '', breed: '', size: '', top_k: 10 })
const matchFiles = ref([]), matchPreviews = ref([]), matchImageUrls = ref([])
watch(matchForm, () => { matchesShown.value = false })
const browseFilters = reactive({ type: 'all', city: '', district: '', coat_color: '', pattern: '', breed: '', since: '', until: '' })
const coatOptions = ['黑', '白', '灰', '橘', '棕', '奶油', '三花', '玳瑁', '黑白', '灰白', '橘白', '其他']
const patternOptions = ['纯色', '虎斑', '双色', '三花', '玳瑁', '重点色', '斑点', '其他']
const browseItems = ref([]), browseTotal = ref(0), browseOffset = ref(0), browseLimit = 100, myItems = ref([])
const selectedMatchKey = ref(''), matchableItems = computed(() => myItems.value.filter(item => item.type === 'lost' && item.status === 'active'))
const detailItem = ref(null), detailLoading = ref(false)
const reportTarget = ref(null), reportType = ref(''), reportReason = ref(''), adminReports = ref([]), adminPublications = ref([])
const adminType = ref('all'), adminStatus = ref('active')
const filteredAdminPublications = computed(() => adminPublications.value.filter(item =>
  (adminType.value === 'all' || item.type === adminType.value) &&
  (adminStatus.value === 'all' || item.status === adminStatus.value)))
const headers = () => ({ Authorization: `Bearer ${token.value}` })
const errorText = e => { const detail = e.response?.data?.detail; return typeof detail === 'string' ? detail : e.message || '请求失败' }
const isSample = item => ['cat50_sample', 'hellostreetcat_sample', 'dataset_gallery_sample'].includes(item.source_type)
function choose(type) { matchesShown.value = false; if (type === 'lost') { page.value = 'match'; window.scrollTo({ top: 320, behavior: 'smooth' }); return } editingReport.value = null; existingImages.value = []; previews.value.forEach(URL.revokeObjectURL); previews.value = []; files.value = []; Object.assign(form, { type: 'sighting', event_city: '', event_district: '', event_time: '', event_lat: null, event_lng: null, contact: '', desc: { coat_color: '', pattern: '', size: '', breed: '' } }); page.value = 'publish'; window.scrollTo({ top: 320, behavior: 'smooth' }) }
function startEdit(item) { editingReport.value = { type: item.type, id: item.id }; existingImages.value = [...item.images]; previews.value.forEach(URL.revokeObjectURL); files.value = []; previews.value = []; form.type = item.type; form.event_city = item.event_city; form.event_district = item.event_district; form.event_time = item.event_time.replace(' ', 'T'); form.event_lat = item.event_lat ?? null; form.event_lng = item.event_lng ?? null; form.contact = item.contact || ''; form.desc = { ...item.desc }; matchesShown.value = false; page.value = 'publish'; window.scrollTo({ top: 280, behavior: 'smooth' }) }
function logout() { token.value = ''; username.value = ''; role.value = 'user'; matchImageUrls.value = []; myItems.value = []; matchesShown.value = false; localStorage.removeItem('cat_token'); localStorage.removeItem('cat_user'); localStorage.removeItem('cat_role'); page.value = 'publish'; notice.value = '已退出登录' }
async function authenticate() { busy.value = true; try { if (registerMode.value) await axios.post('/api/v2/auth/register', auth); const { data } = await axios.post('/api/v2/auth/login', auth); token.value = data.access_token; username.value = auth.username; role.value = data.role || 'user'; localStorage.setItem('cat_token', token.value); localStorage.setItem('cat_user', username.value); localStorage.setItem('cat_role', role.value); auth.password = ''; authOpen.value = false; notice.value = '登录成功' } catch (e) { notice.value = errorText(e) } finally { busy.value = false } }
function selectFiles(e) { const next = Array.from(e.target.files || []); if (next.length + existingImages.value.length > 5 || next.some(f => !['image/jpeg', 'image/png'].includes(f.type) || f.size > 5 * 1024 * 1024)) { notice.value = '每条线索最多 5 张 JPG/PNG，每张不超过 5MB'; e.target.value = ''; return } previews.value.forEach(URL.revokeObjectURL); files.value = next; previews.value = next.map(URL.createObjectURL) }
function removeFile(i) { URL.revokeObjectURL(previews.value[i]); files.value.splice(i, 1); previews.value.splice(i, 1) }
function selectMatchFiles(e) { const next = Array.from(e.target.files || []); e.target.value = ''; if (!next.length) return; if (next.length > 5 || next.some(f => !['image/jpeg', 'image/png'].includes(f.type) || f.size > 5 * 1024 * 1024)) { notice.value = '查询照片最多 5 张 JPG/PNG，每张不超过 5MB'; return } matchPreviews.value.forEach(URL.revokeObjectURL); matchFiles.value = next; matchPreviews.value = next.map(URL.createObjectURL); matchImageUrls.value = []; matchesShown.value = false }
function removeMatchFile(i) { URL.revokeObjectURL(matchPreviews.value[i]); matchFiles.value.splice(i, 1); matchPreviews.value.splice(i, 1); matchImageUrls.value = []; matchesShown.value = false }
function resetMatchFilters() { Object.assign(matchForm, { city: '', district: '', since: '', until: '', coat_color: '', pattern: '', breed: '', size: '', top_k: 10 }); matchesShown.value = false }
onUnmounted(() => { previews.value.forEach(URL.revokeObjectURL); matchPreviews.value.forEach(URL.revokeObjectURL) })
function useLocation() { if (!navigator.geolocation) { notice.value = '浏览器不支持定位'; return } navigator.geolocation.getCurrentPosition(p => { form.event_lat = p.coords.latitude; form.event_lng = p.coords.longitude; notice.value = '已填入当前位置，请确认这里就是事发地点' }, () => { notice.value = '定位失败，可只填城市和区县' }, { timeout: 10000 }) }
async function publish() {
  if (!token.value) { authOpen.value = true; notice.value = '请先登录'; return }
  if (!form.event_city.trim() || !form.event_district.trim() || !form.event_time) { notice.value = '发现城市、发现区县和发现时间必须填写'; return }
  if (!files.value.length && !existingImages.value.length) { notice.value = '请至少保留一张照片'; return }
  const phone = form.contact.trim()
  const digitCount = (phone.match(/\d/g) || []).length
  if (!/^\+?[0-9][0-9 -]{5,24}$/.test(phone) || digitCount < 7 || digitCount > 15) { notice.value = '请填写有效联系电话（7–15 位数字，可含区号）'; return }
  busy.value = true; matchesShown.value = false
  try {
    const images = [...existingImages.value]
    for (const file of files.value) {
      const body = new FormData(); body.append('image', file)
      const { data } = await axios.post('/api/v2/images', body, { headers: headers() })
      images.push(data.image_url)
    }
    const wasEditing = !!editingReport.value
    const reportType = wasEditing ? editingReport.value.type : 'sighting'
    const payload = { species: 'cat', type: reportType, images, desc: { ...form.desc }, event_city: form.event_city, event_district: form.event_district, event_time: form.event_time.replace('T', ' '), event_lat: form.event_lat, event_lng: form.event_lng, contact: form.contact }
    const id = wasEditing ? editingReport.value.id : (await axios.post('/api/v2/reports/sighting', payload, { headers: headers() })).data.id
    if (wasEditing) await axios.patch(`/api/v2/reports/${reportType}/${id}`, payload, { headers: headers() })
    editingReport.value = null; existingImages.value = []
    previews.value.forEach(URL.revokeObjectURL); previews.value = []; files.value = []
    await loadMine(); page.value = 'mine'
    notice.value = wasEditing ? '发现线索已更新。' : '发现线索已发布，丢猫用户现在可以检索到它。'
  } catch (e) { notice.value = errorText(e) } finally { busy.value = false }
}
async function navigate(target) { page.value = target; if (target === 'match') matchesShown.value = false; if (target === 'browse') await loadBrowse(0); if (target === 'mine' || target === 'match') await loadMine(); if (target === 'admin') await loadAdminReports() }
async function runImageMatch() {
  if (!token.value) { authOpen.value = true; notice.value = '请先登录'; return }
  if (!matchFiles.value.length) { notice.value = '请先选择至少一张查询照片'; return }
  if (matchForm.since && matchForm.until && matchForm.since > matchForm.until) { notice.value = '开始日期不能晚于结束日期'; return }
  busy.value = true; matchesShown.value = false
  try {
    if (matchImageUrls.value.length !== matchFiles.value.length) {
      const urls = []
      for (const file of matchFiles.value) {
        const body = new FormData(); body.append('image', file)
        const { data } = await axios.post('/api/v2/images', body, { headers: headers() })
        urls.push(data.image_url)
      }
      matchImageUrls.value = urls
    }
    const { data } = await axios.post('/api/v2/match/search', { ...matchForm, type: 'lost', images: matchImageUrls.value }, { headers: headers() })
    matches.value = data.results || []; matchesShown.value = true; activeReport.value = null; searchScope.value = 'custom'
    matchTargetType.value = 'sighting'
    notice.value = `匹配完成，找到 ${data.total} 条符合条件的相似线索`
  } catch (e) { notice.value = errorText(e) } finally { busy.value = false }
}
function flag(item, type) { if (!token.value) { authOpen.value = true; notice.value = '请先登录'; return } reportTarget.value = item; reportType.value = type; reportReason.value = '' }
async function sendReport() { busy.value = true; try { await axios.post(`/api/v2/reports/${reportType.value}/${reportTarget.value.id}/report`, { reason: reportReason.value }, { headers: headers() }); reportTarget.value = null; notice.value = '举报已提交，等待管理员审核' } catch (e) { notice.value = errorText(e) } finally { busy.value = false } }
async function loadAdminReports() { if (role.value !== 'admin') return; try { const [reports, publications] = await Promise.all([axios.get('/api/v2/admin/reports', { headers: headers() }), axios.get('/api/v2/admin/publications', { headers: headers() })]); adminReports.value = reports.data.items || []; adminPublications.value = publications.data.items || [] } catch (e) { notice.value = errorText(e) } }
async function deletePublication(item) { if (!window.confirm(`确定删除这条${item.type === 'lost' ? '走失' : '发现'}线索？删除后不会出现在浏览或匹配结果中。`)) return; try { await axios.delete(`/api/v2/admin/publications/${item.type}/${item.id}`, { headers: headers() }); item.status = 'deleted'; notice.value = '线索已删除'; await loadBrowse(0) } catch (e) { notice.value = errorText(e) } }
async function moderate(item, action) { try { const { data } = await axios.patch(`/api/v2/admin/reports/${item.id}`, { action }, { headers: headers() }); item.state = data.state; notice.value = action === 'hide' ? '线索已隐藏' : '举报已驳回' } catch (e) { notice.value = errorText(e) } }
async function loadBrowse(offset = 0) { try { const { data } = await axios.get('/api/v2/browse', { params: { ...browseFilters, limit: browseLimit, offset } }); browseItems.value = data.items; browseTotal.value = data.total; browseOffset.value = offset } catch (e) { notice.value = errorText(e) } }
function resetBrowse() { Object.assign(browseFilters, { type: 'all', city: '', district: '', coat_color: '', pattern: '', breed: '', since: '', until: '' }); loadBrowse(0) }
async function openDetails(item, type) {
  detailItem.value = {
    id: item.id, type, desc: { coat_color: '', pattern: '', breed: '', size: '', ...(item.desc || {}) },
    city: item.event_city ?? item.city ?? '', district: item.event_district ?? item.district ?? '',
    event_time: item.event_time || '', phone: item.contact || '', score: typeof item.score === 'number' ? item.score : null,
    reasons: item.reasons || [], images: item.images?.length ? [...item.images] : [item.image_url].filter(Boolean),
    searchable_image_count: item.gallery_image_count || item.searchable_image_count || item.image_count || 0,
  }
  detailLoading.value = true
  try {
    const requests = []
    if (item.source_type === 'cat50_sample' && item.source_cat_id) {
      requests.push(axios.get(`/api/v2/dataset/cats/${item.source_cat_id}`).then(({ data }) => {
        if (detailItem.value?.id === item.id) detailItem.value.images = data.images || detailItem.value.images
      }))
    }
    if (item.has_phone) {
      requests.push(axios.get(`/api/v2/reports/${type}/${item.id}/phone`).then(({ data }) => {
        if (detailItem.value?.id === item.id) detailItem.value.phone = data.phone || ''
      }))
    }
    await Promise.all(requests)
  } catch (e) { notice.value = errorText(e) } finally { detailLoading.value = false }
}
async function loadMine() { if (!token.value) return; try { const { data } = await axios.get('/api/v2/me/reports', { headers: headers() }); myItems.value = data.items } catch (e) { notice.value = errorText(e) } }
async function viewMatches(item) { if (item.type !== 'lost') { notice.value = '只有丢猫用户可以检索发现线索'; return } selectedMatchKey.value = `${item.type}:${item.id}`; page.value = 'match'; busy.value = true; matchesShown.value = false; try { const { data } = await axios.get(`/api/v2/reports/${item.type}/${item.id}/matches`, { headers: headers() }); activeReport.value = { type: item.type, id: item.id }; matches.value = data.results || []; searchScope.value = data.scope || 'same_city'; matchTargetType.value = 'sighting'; matchesShown.value = true; window.scrollTo({ top: 320, behavior: 'smooth' }) } catch (e) { notice.value = errorText(e) } finally { busy.value = false } }
async function runSelectedMatch() { const item = matchableItems.value.find(row => `${row.type}:${row.id}` === selectedMatchKey.value); if (item) await viewMatches(item) }
async function expandMatches() { if (!activeReport.value) return; try { const { type, id } = activeReport.value; const { data } = await axios.get(`/api/v2/reports/${type}/${id}/matches`, { params: { expand: true }, headers: headers() }); matches.value = data.results || []; searchScope.value = data.scope; notice.value = '已扩大到全部城市' } catch (e) { notice.value = errorText(e) } }
async function closeReport(item) { try { await axios.patch(`/api/v2/reports/${item.type}/${item.id}/status`, { status: 'resolved' }, { headers: headers() }); item.status = 'resolved'; notice.value = '已标记为解决' } catch (e) { notice.value = errorText(e) } }
</script>

<style scoped>
* { box-sizing: border-box; } .shell { min-height: 100vh; background: #f7f8f3; color: #20382b; font-family: Inter, 'Microsoft YaHei', sans-serif; } button, input, select, textarea { font: inherit; } button { cursor: pointer; }
.topbar { max-width: 1160px; margin: auto; min-height: 74px; padding: 12px 22px; display: flex; align-items: center; justify-content: space-between; gap: 20px; } .brand { font-size: 21px; white-space: nowrap; } nav { display: flex; gap: 18px; } nav button, .link { border: 0; background: transparent; color: #5b6d61; padding: 7px; } nav button.active, nav button:hover, .link:hover { color: #237846; } main { max-width: 1160px; margin: auto; padding: 0 22px 80px; }
.hero { border-radius: 26px; padding: 58px 60px; background: linear-gradient(115deg,#e2f1dc,#f6eedc); } .eyebrow, .heading span { color: #318454; font-size: 12px; font-weight: 800; letter-spacing: .06em; } h1 { font-size: clamp(30px,4vw,49px); margin: 12px 0 18px; } h2 { font-size: 27px; margin: 7px 0; } h3 { margin: 8px 0; } .hero > p:not(.eyebrow) { max-width: 630px; color: #63756a; line-height: 1.7; } .actions { display: flex; gap: 12px; margin-top: 24px; flex-wrap: wrap; }
.primary,.secondary { border: 1px solid #2b8050; border-radius: 10px; padding: 12px 19px; font-weight: 700; } .primary { color: white; background: #287d4b; } .primary:hover { background: #1e603b; } .secondary { color: #287d4b; background: white; } .secondary:hover { background: #edf6ef; } .small { padding: 9px 13px; font-size: 13px; } .notice { padding: 12px 16px; border-radius: 10px; margin-top: 20px; background: #e8f5e9; color: #246c3f; }
.content { padding-top: 50px; } .heading { margin-bottom: 22px; } .heading p { color: #79877d; margin: 7px 0; }
.panel,.dialog { background: white; border: 1px solid #e3e9e0; box-shadow: 0 12px 30px #233c290a; border-radius: 20px; padding: 28px; } .grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 20px; } label { display: flex; flex-direction: column; gap: 8px; font-size: 14px; font-weight: 700; } input,select,textarea { border: 1px solid #dbe4db; border-radius: 9px; background: white; color: #20382b; padding: 11px 12px; width: 100%; outline: none; } input:focus,select:focus,textarea:focus { border-color: #3e9b61; box-shadow: 0 0 0 3px #3e9b6125; } .location { display: flex; align-items: center; gap: 14px; background: #f7f9f4; border-radius: 12px; padding: 14px; margin: 22px 0; } .location > div { flex: 1; } .location p,.tip { font-size: 12px; color: #839086; margin: 5px 0; } .location span { font-size: 12px; color: #267a47; } .upload { border: 2px dashed #cbdccc; border-radius: 12px; padding: 18px; cursor: pointer; } .upload small { color: #839086; font-weight: 400; } .upload input { border: 0; padding-left: 0; } .previews { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; } .previews > div { width: 110px; height: 110px; position: relative; } .previews img { width: 100%; height: 100%; border-radius: 9px; object-fit: cover; } .previews button { position: absolute; top: 3px; right: 3px; border: 0; border-radius: 50%; background: #263b2e; color: white; } .tip { margin: 18px 0; } .submit { width: 100%; } .submit:disabled { opacity: .6; cursor: wait; }
.results,.inbox { margin-top: 48px; } .result-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; } .result { display: flex; gap: 15px; border: 1px solid #e3e9e0; border-radius: 15px; background: white; padding: 13px; } .result > img { width: 142px; height: 155px; border-radius: 9px; object-fit: cover; } .result p,.result small { color: #718075; font-size: 13px; margin: 7px 0; } .empty { background: white; border: 1px solid #e3e9e0; border-radius: 15px; padding: 35px; text-align: center; color: #7d8b80; } .filters { display: flex; gap: 10px; margin-bottom: 20px; max-width: 590px; } .filters select { width: 155px; }
.my-list { display: grid; gap: 12px; } .my-item,.message { border: 1px solid #e3e9e0; background: white; border-radius: 13px; padding: 12px; } .my-item { display: flex; align-items: center; gap: 16px; } .my-item img { width: 90px; height: 90px; object-fit: cover; border-radius: 8px; } .my-item p { color: #7a897d; margin: 7px 0; } .my-actions { margin-left: auto; display: grid; gap: 6px; } .message { margin: 10px 0; } .message small { color: #7a897d; } .message > div { display: flex; gap: 8px; margin-top: 12px; }
.overlay { position: fixed; inset: 0; background: #112919a6; z-index: 10; display: grid; place-items: center; padding: 20px; } .dialog { position: relative; width: min(440px,100%); display: grid; gap: 15px; } .dialog h2 { margin: 0; } .dialog p { color: #718075; margin: 0; } .close { position: absolute; right: 14px; top: 10px; border: 0; background: none; font-size: 28px; }
.match-panel { display: flex; gap: 15px; align-items: end; max-width: 760px; } .match-panel label { flex: 1; }
.match-upload { margin-top: 22px; } .match-reset { margin: 6px 0 12px; } .saved-match { margin-top: 25px; } .saved-match summary { cursor: pointer; color: #267a47; font-weight: 700; margin-bottom: 12px; }
.admin-toolbar { display: flex; gap: 12px; align-items: end; margin-bottom: 18px; flex-wrap: wrap; } .admin-toolbar label { min-width: 160px; } .admin-item { margin-bottom: 10px; } .delete-button { margin-left: auto; border-color: #b84c43; color: #a33b31; } .admin-reports-heading { margin-top: 40px; }
.browse-filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 15px; margin-bottom: 18px; }
.filter-actions { display: flex; align-items: end; gap: 8px; }
.browse-count { color: #65786a; margin: 10px 0 18px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 16px; margin-top: 24px; }
.detail-dialog { width: min(800px, 100%); max-height: 88vh; overflow: auto; }
.detail-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.detail-grid > div { display: grid; gap: 4px; padding: 12px; border-radius: 10px; background: #f5f8f3; }
.detail-grid small { color: #7a897d; }
.dataset-photos { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.dataset-photos img { width: 100%; height: 135px; object-fit: cover; border-radius: 8px; }
@media(max-width:900px){ .browse-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media(max-width:600px){ .browse-filters,.detail-grid { grid-template-columns: 1fr; } .dataset-photos { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media(max-width:750px){ .topbar { flex-wrap: wrap; padding: 16px; } nav { order: 3; width: 100%; justify-content: space-between; flex-wrap: wrap; gap: 3px; } nav button { font-size: 13px; } main { padding: 0 16px 60px; } .hero { padding: 34px 25px; } .grid,.result-grid { grid-template-columns: 1fr; } .location,.match-panel { flex-wrap: wrap; } .result > img { width: 110px; height: 130px; } .my-item { flex-wrap: wrap; } .my-actions { margin-left: 0; display: flex; width: 100%; } }
</style>
