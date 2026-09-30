<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
const emit = defineEmits(['selected'])
const batches = ref([])
const segments = ref([])
const selectedBatch = ref(null)
const selectedSegment = ref(null)
const form = ref({ code:'', name:'' })
const windowForm = ref({ window_start:'', window_end:'' })
const error = ref('')
async function load() {
  batches.value = await api.get('/api/batches')
}
async function createBatch() {
  error.value = ''
  try { await api.post('/api/batches', form.value); form.value = {code:'',name:''}; await load() }
  catch(e){ error.value = e.message }
}
async function chooseBatch(b) {
  selectedBatch.value = b
  segments.value = await api.get(`/api/batches/${b.id}/segments`)
}
function chooseSegment(s) { selectedSegment.value = s; emit('selected', s) }
async function adjustWindow() {
  error.value = ''
  try {
    const s = await api.patch(`/api/batches/segments/${selectedSegment.value.id}`, windowForm.value)
    await chooseBatch(selectedBatch.value); chooseSegment(s)
  } catch(e){ error.value = e.message }
}
onMounted(load)
defineExpose({ refresh:load })
</script>
<template>
  <div class="card">
    <h2>批次与稳定窗口</h2>
    <div v-if="error" class="notice">{{ error }}</div>
    <input v-model="form.code" placeholder="批次代码" />
    <input v-model="form.name" placeholder="批次名称" />
    <button @click="createBatch">创建批次</button>
    <h3>批次</h3>
    <table><thead><tr><th>代码</th><th>状态</th><th></th></tr></thead><tbody>
      <tr v-for="b in batches" :key="b.id"><td>{{b.code}}</td><td>{{b.status}}</td>
      <td><button class="secondary" @click="chooseBatch(b)">打开</button></td></tr>
    </tbody></table>
    <h3 v-if="selectedBatch">批段</h3>
    <table v-if="selectedBatch"><thead><tr><th>代码</th><th>版本</th><th>窗口</th><th></th></tr></thead><tbody>
      <tr v-for="s in segments" :key="s.id"><td>{{s.code}}</td><td>v{{s.version}}</td>
      <td>{{new Date(s.window_start).toLocaleString()}} → {{new Date(s.window_end).toLocaleString()}}</td>
      <td><button @click="chooseSegment(s)">选择</button></td></tr>
    </tbody></table>
    <div v-if="selectedSegment">
      <h3>工程师调整窗口</h3>
      <p class="muted">调整后依赖计算立即过期；旧任务完成也不会覆盖当前图。</p>
      <input type="datetime-local" v-model="windowForm.window_start">
      <input type="datetime-local" v-model="windowForm.window_end">
      <button @click="adjustWindow">调整并升版</button>
    </div>
  </div>
</template>
