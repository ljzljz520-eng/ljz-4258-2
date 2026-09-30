<script setup>
import { ref } from 'vue'
import BatchPanel from './components/BatchPanel.vue'
import TopologyPanel from './components/TopologyPanel.vue'
import MeasurementPanel from './components/MeasurementPanel.vue'
import ResultPanel from './components/ResultPanel.vue'
import { api } from './lib/api'
const selected = ref(null)
const notes = ref('')
const nodes = ref([]), edges = ref([]), resultKey = ref(0)
async function onSelected(s) {
  selected.value = s
  await loadTopology()
  resultKey.value++
}
async function loadTopology() {
  if (!selected.value) return
  nodes.value = await api.get(`/api/segments/${selected.value.id}/nodes`)
  edges.value = await api.get(`/api/segments/${selected.value.id}/edges`)
}
async function changed() { await loadTopology(); resultKey.value++ }
async function loadNotes() {
  const data = await api.get('/api/engineering-notes')
  notes.value = `${data.time_alignment} ${data.missing_data} ${data.safety_scope}`
}
loadNotes()
async function processOne() {
  const claim = await api.post('/api/worker/claim', {worker_id:'browser-debug'})
  if(claim) await api.post(`/api/worker/jobs/${claim.id}/complete`)
}
</script>
<template>
<header>
  <h1>乳脂分离与回配核算平台</h1>
  <p>质量/脂肪守恒、跨批回流与罐底旧料统一闭合；仅核算与展示，不推荐回配比例或控制设备。</p>
</header>
<main>
  <div class="grid">
    <BatchPanel @selected="onSelected" />
    <div>
      <div class="notice" style="margin-bottom:14px">
        流程可在下方编辑；计算前先做可辨识性检查。欠定时只返回缺失测量及可行区间，不强行生成唯一图。
        生产环境由独立 Worker 轮询任务；调试时可<button class="secondary" @click="processOne">执行一个队列任务</button>。
      </div>
      <template v-if="selected">
        <TopologyPanel :key="selected.id" :segment="selected" @changed="changed" style="margin-bottom:16px"/>
        <MeasurementPanel :key="selected.id" :segment="selected" :nodes="nodes" :edges="edges" style="margin-bottom:16px"/>
        <ResultPanel :key="selected.id" :segment="selected" :refresh-key="resultKey"/>
      </template>
      <div v-else class="card">请选择或创建一个批段。</div>
      <div class="card" style="margin-top:16px"><h2>取舍说明</h2><p class="muted">{{ notes }}</p></div>
    </div>
  </div>
</main>
</template>
