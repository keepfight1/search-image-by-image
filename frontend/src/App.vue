<template>
  <div class="container">
    <h1>宠物寻回匹配平台</h1>

    <!-- 信息发布表单 -->
    <div class="form-card">
      <div class="row">
        <label>信息类型 <span class="required">*</span></label>
        <div class="radio-group">
          <label><input v-model="infoType" value="lost" type="radio"> 宠物走失</label>
          <label><input v-model="infoType" value="sight" type="radio"> 疑似流浪宠物目击</label>
        </div>
      </div>

      <div class="row">
        <label>动物类别 <span class="required">*</span></label>
        <select v-model="animalType">
          <option value="cat">猫咪</option>
          <option value="dog">狗狗</option>
          <option value="other">其他</option>
        </select>
      </div>

      <div class="row">
        <label>事件地点（走失/目击发生地）<span class="required">*</span></label>
        <input v-model="eventArea" placeholder="例如：洪山区">
        <p class="tip-small">⚠️ 这里是宠物丢失/被看见的地点，不是你当前上传位置</p>
      </div>

      <div class="row">
        <label>事件时间（走失/目击时间）<span class="required">*</span></label>
        <input v-model="eventTime" type="datetime-local">
      </div>

      <div class="row">
        <label>外貌描述（毛色、花纹、体型等，辅助匹配加分）<span class="required">*</span></label>
        <textarea v-model="desc" rows="3" placeholder="示例：橘白相间，右耳缺一块，短腿"></textarea>
        <p class="tip-small">仅作为辅助加分，不会因为描述不符直接筛掉候选</p>
      </div>

      <div class="row">
        <label>联系方式（自愿公开，匹配成功后可见）</label>
        <input v-model="contact" placeholder="选填">
      </div>

      <div class="row">
        <label>当前上传位置（用于定位，可获取/手动填写）<span class="required">*</span></label>
        <div class="loc-row">
          <input v-model="uploadArea" placeholder="点击获取当前位置，失败可手动填写">
          <button type="button" @click="getLocation" class="loc-btn">获取定位</button>
        </div>
        <p class="tip-small">上传位置 ≠ 事件地点，仅辅助计算距离，不参与筛选</p>
      </div>

      <!-- 图片上传 -->
      <div class="upload-area"
           @click="triggerInput"
           @dragover.prevent="isDragover=true"
           @dragleave="isDragover=false"
           @drop.prevent="onDrop"
           :class="{dragover:isDragover}">
        <input ref="fileInput" type="file" accept="image/*" @change="onFileSelect" hidden>
        <div v-if="!imgSrc" class="upload-placeholder">
          <div class="upload-icon">📷</div>
          <p>点击或拖拽宠物图片上传</p>
        </div>
        <div v-else class="preview-wrap">
          <img :src="imgSrc" class="preview-img">
          <div class="change-img" @click.stop="triggerInput">更换图片</div>
        </div>
      </div>

      <div class="btn-row">
        <button class="search-btn" @click="startMatch" :disabled="loading || !imgSrc">
          {{ loading ? "匹配检索中..." : "开始匹配" }}
        </button>
        <button class="reset-btn" @click="resetForm" :disabled="loading">重置表单</button>
      </div>
    </div>

    <!-- 匹配结果区域 -->
    <div class="result-card" v-if="showResult">
      <div class="result-head">
        <h3>匹配候选列表（最多5条）</h3>
        <button class="expand-btn" @click="expandCitySearch" :disabled="loading">
          {{ loading ? "搜索中..." : "手动扩大至全市搜索" }}
        </button>
      </div>
      <p class="warn-tip">⚠️ 相似度仅用于排序，不代表找回概率；文本描述仅做加分，不做硬性过滤</p>

      <div v-if="loading" class="skeleton-wrap">
        <div class="skeleton-item" v-for="n in 2" :key="n">
          <div class="skeleton-img"></div>
          <div class="skeleton-info">
            <div class="skeleton-line w60"></div>
            <div class="skeleton-line w40"></div>
            <div class="skeleton-line w80"></div>
          </div>
        </div>
      </div>

      <div v-else-if="resultList.length === 0" class="empty">
        <div class="empty-icon">🐾</div>
        <p>暂无可靠线索</p>
        <p class="empty-sub">可尝试手动扩大至全市搜索</p>
      </div>

      <template v-else>
        <div class="item" v-for="(item, idx) in resultList" :key="idx">
          <img :src="item.img" class="item-img">
          <div class="item-info">
            <div class="item-title">
              <b>{{ item.animalType === 'cat' ? '猫咪' : item.animalType === 'dog' ? '狗狗' : '其他' }}</b>
              <span class="badge">{{ item.eventArea }}</span>
            </div>
            <div><b>事件时间：</b>{{ item.eventTime }}</div>
            <div><b>距离：</b>{{ item.distance }}</div>
            <div><b>外貌描述：</b>{{ item.desc }}</div>
            <div>
              <b>相似度：</b>
              <span class="score-bar">
                <span class="score-fill" :style="{width:(item.score*100)+'%'}"></span>
                <em>{{ (item.score*100).toFixed(1) }}%</em>
              </span>
            </div>
            <div class="item-actions">
              <button class="detail-btn" @click="openDetail(item)">查看详情</button>
              <button class="contact-btn" @click="openContact(item)">联系TA</button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 详情弹窗 -->
    <div class="mask" v-if="detailShow" @click.self="closeDetail">
      <div class="detail-modal">
        <div class="modal-head">
          <h2>候选详情</h2>
          <span class="close" @click="closeDetail">×</span>
        </div>
        <div class="modal-body">
          <img :src="currentDetail.img" class="modal-img" />
          <div class="info-line"><b>信息类型：</b>{{ currentDetail.infoType === 'lost' ? '宠物走失' : '疑似流浪目击' }}</div>
          <div class="info-line"><b>动物类别：</b>{{ currentDetail.animalType === 'cat' ? '猫咪' : currentDetail.animalType === 'dog' ? '狗狗' : '其他' }}</div>
          <div class="info-line"><b>事件地点：</b>{{ currentDetail.eventArea }}</div>
          <div class="info-line"><b>事件时间：</b>{{ currentDetail.eventTime }}</div>
          <div class="info-line"><b>距离：</b>{{ currentDetail.distance }}</div>
          <div class="info-line"><b>外貌描述：</b>{{ currentDetail.desc }}</div>
          <div class="info-line"><b>相似度（排序用）：</b>{{ (currentDetail.score*100).toFixed(2) }}%</div>
          <div class="info-line" v-if="currentDetail.contact"><b>联系方式：</b>{{ currentDetail.contact }}</div>
          <div class="info-line" v-else><b>联系方式：</b>未公开</div>
        </div>
      </div>
    </div>

    <!-- 联系弹窗 -->
    <div class="mask" v-if="contactShow" @click.self="contactShow=false">
      <div class="contact-modal">
        <div class="modal-head">
          <h2>联系方式</h2>
          <span class="close" @click="contactShow=false">×</span>
        </div>
        <div class="modal-body center">
          <div v-if="currentContact">
            <p class="contact-label">对方公开联系号码</p>
            <p class="contact-number">{{ currentContact }}</p>
            <p class="contact-tip">请说明是在宠物寻回平台看到的信息</p>
          </div>
          <div v-else>
            <p>该用户没有公开联系方式</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 返回顶部 -->
    <button class="back-top" v-if="showBackTop" @click="scrollToTop">↑</button>
  </div>
</template>

<script setup>
import {ref, onMounted, onUnmounted} from 'vue'

// 表单数据
const infoType = ref('lost')
const animalType = ref('cat')
const eventArea = ref('')
const eventTime = ref('') // 事件时间：用户填写，必填
const desc = ref('')
const contact = ref('')
const uploadArea = ref('') // 上传位置：必填
// 上传时间：提交瞬间自动生成，不展示给用户，传给后端
let uploadTime = ''

const fileInput = ref(null)
const imgSrc = ref('')
const selectFile = ref(null)
const isDragover = ref(false)
const loading = ref(false)
const showResult = ref(false)
const resultList = ref([])

// 弹窗
const detailShow = ref(false)
const currentDetail = ref({})
const contactShow = ref(false)
const currentContact = ref('')

// 返回顶部
const showBackTop = ref(false)
function onScroll(){
  showBackTop.value = window.scrollY > 300
}
function scrollToTop(){
  window.scrollTo({top:0, behavior:'smooth'})
}
onMounted(()=>window.addEventListener('scroll', onScroll))
onUnmounted(()=>window.removeEventListener('scroll', onScroll))

// 获取浏览器定位
function getLocation(){
  if(!navigator.geolocation){
    alert("浏览器不支持定位，请手动填写上传位置")
    return
  }
  navigator.geolocation.getCurrentPosition(
    (pos)=>{
      uploadArea.value = "定位获取成功（前端模拟）"
    },
    ()=>{
      alert("定位失败，请手动填写上传位置")
    }
  )
}

function triggerInput(){
  fileInput.value.click()
}
function onDrop(e){
  isDragover.value = false
  const f = e.dataTransfer.files[0]
  if(f && f.type.startsWith('image/')) handleFile(f)
}
function onFileSelect(e){
  const f = e.target.files[0]
  if(!f) return
  handleFile(f)
}
function handleFile(file){
  selectFile.value = file
  const reader = new FileReader()
  reader.onload = ev=>{
    imgSrc.value = ev.target.result
    showResult.value = false
    resultList.value = []
  }
  reader.readAsDataURL(file)
}

function openDetail(row){
  currentDetail.value = row
  detailShow.value = true
}
function closeDetail(){
  detailShow.value = false
}
function openContact(row){
  currentContact.value = row.contact || ''
  contactShow.value = true
}

function resetForm(){
  infoType.value = 'lost'
  animalType.value = 'cat'
  eventArea.value = ''
  eventTime.value = ''
  desc.value = ''
  contact.value = ''
  uploadArea.value = ''
  imgSrc.value = ''
  selectFile.value = null
  showResult.value = false
  resultList.value = []
}

// ========= 匹配模拟库 =========
const lostLib = [
  {img:"https://picsum.photos/id/40/220/220",animalType:"cat",eventArea:"洪山区",eventTime:"2026-10-20 18:30",distance:"1.2km",desc:"橘白，右耳缺角，短毛",score:0.93,contact:"138xxxx1111",infoType:"lost"},
  {img:"https://picsum.photos/id/41/220/220",animalType:"cat",eventArea:"洪山区",eventTime:"2026-10-21 08:10",distance:"2.5km",desc:"纯黑白爪公猫",score:0.86,contact:"",infoType:"lost"},
  {img:"https://picsum.photos/id/42/220/220",animalType:"cat",eventArea:"武昌区",eventTime:"2026-10-20 22:00",distance:"7.8km",desc:"三花圆脸胆小",score:0.81,contact:"139xxxx2222",infoType:"lost"},
]
const sightLib = [
  {img:"https://picsum.photos/id/43/220/220",animalType:"cat",eventArea:"江岸区",eventTime:"2026-10-19 16:00",distance:"12km",desc:"英短蓝猫，胖，无项圈",score:0.77,contact:"",infoType:"sight"},
  {img:"https://picsum.photos/id/44/220/220",animalType:"cat",eventArea:"江夏区",eventTime:"2026-10-21 07:20",distance:"18km",desc:"橘猫尾巴尖白色",score:0.72,contact:"137xxxx3333",infoType:"sight"},
]

// 开始匹配：表单校验 + 自动记录上传时间
async function startMatch(){
  if(!eventArea.value.trim()){
    alert('请填写事件地点（走失/目击发生区域）')
    return
  }
  if(!eventTime.value.trim()){
    alert('请填写事件时间（走失/目击时间）')
    return
  }
  if(!uploadArea.value.trim()){
    alert('请填写当前上传位置，可以点击获取定位或者手动输入')
    return
  }
  if(!desc.value.trim()){
    alert('请填写外貌描述')
    return
  }
  if(!selectFile.value){
    alert('请上传宠物图片')
    return
  }

  // 提交瞬间自动记录上传时间，对接后端直接传给接口
  uploadTime = new Date().toISOString()
  console.log('本次提交的上传时间(给后端):', uploadTime)

  loading.value = true
  showResult.value = true
  resultList.value = []
  await new Promise(r=>setTimeout(r,1200))

  let targetLib = infoType.value === 'lost' ? sightLib : lostLib
  let sameTypeList = targetLib.filter(item=>item.animalType === animalType.value)
  let areaList = sameTypeList.filter(item=>item.eventArea === eventArea.value.trim())
  const threshold = 0.7
  let validArea = areaList.filter(x=>x.score >= threshold)

  if(validArea.length > 0){
    resultList.value = validArea.sort((a,b)=>b.score - a.score).slice(0,5)
  }else{
    let cityAll = sameTypeList.filter(x=>x.score >= threshold)
    if(cityAll.length>0){
      resultList.value = cityAll.sort((a,b)=>b.score - a.score).slice(0,5)
    }else{
      resultList.value = []
    }
  }
  loading.value = false
}

async function expandCitySearch(){
  loading.value = true
  resultList.value = []
  await new Promise(r=>setTimeout(r,1200))
  let targetLib = infoType.value === 'lost' ? sightLib : lostLib
  let cityAll = targetLib.filter(item=>item.animalType === animalType.value && item.score >= 0.7)
  resultList.value = cityAll.sort((a,b)=>b.score - a.score).slice(0,5)
  loading.value = false
}
</script>

<style scoped>
*{box-sizing:border-box;margin:0;padding:0}
.container{max-width:920px;margin:30px auto;padding:0 20px 60px;font-family:system-ui}
h1{text-align:center;margin-bottom:24px;color:#222}
.form-card{border:1px solid #e5e5e5;border-radius:12px;padding:24px;margin-bottom:24px;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.row{margin-bottom:16px}
label{display:block;margin-bottom:6px;font-weight:500;color:#333}
.required{color:#e04040;margin-left:2px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:15px;outline:none;transition:border-color .2s}
input:focus,select:focus,textarea:focus{border-color:#2b85d9}
.radio-group{display:flex;gap:24px}
.radio-group label{display:flex;align-items:center;gap:6px;cursor:pointer;font-weight:normal}
.radio-group input{width:auto}
.tip-small{font-size:12px;color:#777;margin-top:4px}
.loc-row{display:flex;gap:8px}
.loc-row input{flex:1}
.loc-btn{white-space:nowrap;padding:0 12px;border:1px solid #2b85d9;background:#fff;color:#2b85d9;border-radius:6px;cursor:pointer}

.upload-area{width:100%;height:220px;border:2px dashed #ccc;border-radius:10px;display:flex;align-items:center;justify-content:center;cursor:pointer;margin:16px 0;transition:.2s;position:relative;overflow:hidden}
.upload-area.dragover{border-color:#2b85d9;background:#f0f7ff}
.upload-placeholder{text-align:center;color:#999}
.upload-icon{font-size:40px;margin-bottom:8px}
.preview-wrap{position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center}
.preview-img{max-height:100%;max-width:100%;object-fit:contain}
.change-img{position:absolute;top:10px;right:10px;background:rgba(0,0,0,0.6);color:#fff;padding:6px 12px;border-radius:6px;font-size:13px;cursor:pointer}
.change-img:hover{background:rgba(0,0,0,0.8)}

.btn-row{display:flex;gap:12px;margin-top:8px}
.search-btn{flex:1;padding:12px;border:none;background:#2b85d9;color:#fff;border-radius:8px;font-size:16px;cursor:pointer;transition:.2s}
.search-btn:hover{background:#1e6fb8}
.search-btn:disabled{background:#9dc3e6;cursor:not-allowed}
.reset-btn{padding:12px 24px;border:1px solid #ccc;background:#fff;color:#666;border-radius:8px;font-size:16px;cursor:pointer}
.reset-btn:hover{background:#f5f5f5}

.result-card{border:1px solid #e5e5e5;border-radius:12px;padding:24px;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.result-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.expand-btn{padding:6px 14px;border:1px solid #2b85d9;background:#fff;color:#2b85d9;border-radius:6px;cursor:pointer;font-size:14px}
.expand-btn:hover{background:#f0f7ff}
.expand-btn:disabled{opacity:0.6;cursor:not-allowed}
.warn-tip{color:#d44333;font-size:14px;margin-bottom:16px}

.empty{padding:50px 20px;text-align:center;color:#999}
.empty-icon{font-size:48px;margin-bottom:12px}
.empty-sub{font-size:13px;margin-top:6px;color:#bbb}

.item{display:flex;gap:16px;border:1px solid #eee;border-radius:10px;padding:14px;margin-bottom:14px}
.item-img{width:160px;height:160px;object-fit:cover;border-radius:8px;flex-shrink:0}
.item-info{flex:1;display:flex;flex-direction:column;gap:6px;font-size:14px;color:#444}
.item-title{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.badge{background:#e8f2fc;color:#2b85d9;font-size:12px;padding:2px 8px;border-radius:10px}
.item-actions{display:flex;gap:8px;margin-top:6px}
.detail-btn{padding:6px 14px;border:none;background:#666;color:#fff;border-radius:6px;cursor:pointer;font-size:13px}
.detail-btn:hover{background:#444}
.contact-btn{padding:6px 14px;border:none;background:#2b85d9;color:#fff;border-radius:6px;cursor:pointer;font-size:13px}
.contact-btn:hover{background:#1e6fb8}

.score-bar{display:inline-flex;align-items:center;gap:6px}
.score-fill{width:80px;height:8px;background:#eee;border-radius:4px;overflow:hidden;display:inline-block;position:relative}
.score-fill::after{content:'';display:block;height:100%;background:linear-gradient(90deg,#42b983,#2b85d9);border-radius:4px}
.score-bar em{font-style:normal;font-size:13px;color:#42b983;font-weight:bold}

.skeleton-wrap{padding:20px 0}
.skeleton-item{display:flex;gap:16px;margin-bottom:20px}
.skeleton-img{width:160px;height:160px;background:#eee;border-radius:8px;flex-shrink:0;animation:shimmer 1.5s infinite}
.skeleton-info{flex:1;display:flex;flex-direction:column;gap:10px}
.skeleton-line{height:14px;background:#eee;border-radius:4px;animation:shimmer 1.5s infinite}
.w60{width:60%}.w40{width:40%}.w80{width:80%}
@keyframes shimmer{0%{opacity:1}50%{opacity:.5}100%{opacity:1}}

.mask{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:999}
.detail-modal,.contact-modal{width:520px;max-width:90vw;background:#fff;border-radius:12px;overflow:hidden}
.modal-head{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #eee}
.close{font-size:28px;cursor:pointer;color:#999;line-height:1}
.close:hover{color:#333}
.modal-body{padding:20px}
.modal-img{width:100%;height:300px;object-fit:contain;margin-bottom:16px;border-radius:8px;background:#f5f5f5}
.info-line{margin:8px 0;font-size:15px;color:#444}
.modal-body.center{text-align:center;padding:30px 20px}
.contact-label{color:#999;font-size:14px;margin-bottom:8px}
.contact-number{font-size:28px;color:#2b85d9;font-weight:bold;margin-bottom:12px;letter-spacing:1px}
.contact-tip{color:#999;font-size:13px;margin-top:16px}

.back-top{position:fixed;right:30px;bottom:40px;width:44px;height:44px;border-radius:50%;border:none;background:#2b85d9;color:#fff;font-size:20px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.2);z-index:100}
.back-top:hover{background:#1e6fb8}
</style>
