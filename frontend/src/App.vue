<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from './api'
import TopologyView from './components/TopologyView.vue'
import ClosureChart from './components/ClosureChart.vue'
import DiagnosticsPanel from './components/DiagnosticsPanel.vue'
import SignoffPanel from './components/SignoffPanel.vue'
import WindowEditor from './components/WindowEditor.vue'
import DetailsContent from './components/DetailsContent.vue'

const health = ref(null)
const topologies = ref([])
const batches = ref([])
const selectedBatchId = ref(null)
const batch = ref(null)
const windows = ref([])
const selectedWindowId = ref(null)
const result = ref(null)
const jobs = ref([])
const busy = ref(false)
const error = ref('')
const tab = ref('closure')

const selectedWindow = computed(() =>
  windows.value.find(w => w.id === selectedWindowId.value))

async function refreshAll() {
  health.value = await api.health()
  topologies.value = await api.topologies()
  batches.value = await api.batches()
  if (!selectedBatchId.value && batches.value.length) {
    selectedBatchId.value = batches.value[0].id
  }
  await loadBatch()
}

async function loadBatch() {
  if (!selectedBatchId.value) return
  batch.value = await api.batch(selectedBatchId.value)
  windows.value = await api.windows(selectedBatchId.value)
  if (!selectedWindowId.value && windows.value.length) {
    selectedWindowId.value = windows.value[0].id
  }
  await refreshResult()
  await loadJobs()
}

async function loadJobs() {
  if (!selectedWindowId.value) return
  jobs.value = await api.jobs(selectedWindowId.value)
}

async function refreshResult() {
  error.value = ''
  if (!selectedWindowId.value) return
  try {
    result.value = await api.result(selectedWindowId.value)
  } catch (e) {
    result.value = null
  }
}

async function onWindowCreated(win) {
  selectedWindowId.value = win.id
  await loadBatch()
}

async function runPreview() {
  busy.value = true; error.value = ''
  try {
    const r = await api.preview(selectedWindowId.value)
    result.value = { status: r.status, payload: r, preview: true }
    tab.value = r.status === 'identified' ? 'closure' : 'diagnostics'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}

async function runJob() {
  busy.value = true; error.value = ''
  try {
    await api.enqueue(selectedWindowId.value)
    await loadJobs()
    error.value = '已入队；由独立 Worker 进程计算，可用“轮询等待”查看结果。'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}

async function poll() {
  busy.value = true
  try {
    for (let i = 0; i < 20; i++) {
      await loadJobs()
      const latest = jobs.value[0]
      if (latest && ['done', 'stale', 'error', 'superseded']
          .includes(latest.status)) break
      await new Promise(r => setTimeout(r, 500))
    }
    await refreshResult()
  } finally { busy.value = false }
}

onMounted(refreshAll)
</script>

<template>
  <header>
    <h1>乳脂分离与回配核算平台</h1>
    <span class="badge">算法版本 {{ health?.algorithm_version }}</span>
    <span class="badge">质量 / 脂肪双守恒</span>
  </header>
  <div class="layout">
    <aside>
      <div class="section">
        <h2>批次</h2>
        <select v-model.number="selectedBatchId" @change="loadBatch"
                style="width:100%">
          <option v-for="b in batches" :key="b.id" :value="b.id">
            {{ b.code }}
          </option>
        </select>
      </div>

      <WindowEditor :batch-id="selectedBatchId" :batch="batch"
                    :windows="windows" :selected-id="selectedWindowId"
                    @select="selectedWindowId = $event"
                    @created="onWindowCreated"
                    @changed="loadBatch" />

      <div class="section" v-if="selectedWindow">
        <h2>计算</h2>
        <div class="row">
          <button :disabled="busy" @click="runPreview">试算（不入队）</button>
          <button class="ghost" :disabled="busy" @click="runJob">入队作业</button>
        </div>
        <div class="row" style="margin-top:8px">
          <button class="ghost" :disabled="busy" @click="poll">
            轮询等待 Worker</button>
        </div>
        <div class="error" v-if="error">{{ error }}</div>
      </div>

      <div class="section" v-if="jobs.length">
        <h2>最近作业</h2>
        <div v-for="j in jobs.slice(0, 5)" :key="j.id" class="list-item"
             style="cursor:default">
          <div class="row" style="justify-content:space-between">
            <strong>#{{ j.id }}</strong>
            <span class="pill"
                  :class="j.status==='done' ? 'ok' :
                          (j.status==='stale'||j.status==='error') ? 'bad'
                          : 'warn'">
              {{ j.status }}
            </span>
          </div>
          <div class="muted mono">{{ j.input_digest.slice(0,16) }}…
            · current={{ j.is_current }}</div>
          <div class="muted" v-if="j.error">{{ j.error.slice(0, 120) }}</div>
        </div>
      </div>
    </aside>

    <main>
      <div class="notice">{{ health?.platform_notice }}</div>

      <div class="card" v-if="batch && topologies.length">
        <TopologyView :batch="batch" :topologies="topologies"
                      :payload="result?.payload" />
      </div>

      <div class="tabbar" v-if="result">
        <button :class="{active: tab==='closure'}" @click="tab='closure'">
          闭合残差</button>
        <button :class="{active: tab==='diagnostics'}"
                @click="tab='diagnostics'">
          可辨识性 / 缺测诊断</button>
        <button :class="{active: tab==='details'}" @click="tab='details'">
          段流结果与存量</button>
        <button :class="{active: tab==='signoff'}" @click="tab='signoff'">
          签署冻结</button>
      </div>

      <ClosureChart v-if="tab==='closure' && result" :result="result" />
      <DiagnosticsPanel v-if="tab==='diagnostics' && result" :result="result" />
      <DetailsContent v-if="tab==='details' && result" :result="result" />
      <SignoffPanel v-if="tab==='signoff'" :window-id="selectedWindowId"
                    :result="result" @signed="refreshResult" />
    </main>
  </div>
</template>
