<script setup>
import { ref } from 'vue'
import { api } from '../api'

const props = defineProps({
  batchId: Number,
  batch: Object,
  windows: Array,
  selectedId: Number
})
const emit = defineEmits(['select', 'created', 'changed'])
const label = ref('新稳定窗口')
const maxGap = ref(2000)
const extrap = ref(700)
const selectedSegs = ref([])
const err = ref('')

function toggleSeg(id) {
  const i = selectedSegs.value.indexOf(id)
  if (i >= 0) selectedSegs.value.splice(i, 1)
  else selectedSegs.value.push(id)
}

async function create() {
  err.value = ''
  try {
    const win = await api.createWindow(props.batchId, {
      label: label.value,
      segment_ids: [...selectedSegs.value].sort((a, b) => a - b),
      max_gap_s: Number(maxGap.value),
      extrap_tolerance_s: Number(extrap.value)
    })
    selectedSegs.value = []
    emit('created', win)
  } catch (e) { err.value = e.message }
}
</script>

<template>
  <div class="section">
    <h2>稳定窗口</h2>
    <div v-for="w in windows" :key="w.id"
         class="list-item"
         :class="{ active: w.id === selectedId }"
         @click="emit('select', w.id)">
      <div class="row" style="justify-content:space-between">
        <strong>{{ w.label }}</strong>
        <span class="muted">#{{ w.id }}</span>
      </div>
      <div class="muted">段 {{ w.segment_ids.length }} 个 ·
        最大间隔 {{ w.max_gap_s }}s ·
        外推容差 {{ w.extrap_tolerance_s }}s</div>
      <div class="muted" v-if="w.superseded_by">
        已被窗口 #{{ w.superseded_by }} 调整取代</div>
    </div>

    <div class="card" v-if="batch">
      <div class="muted" style="margin-bottom:6px">新窗口 / 调整工程师窗口
      </div>
      <label class="muted">名称</label>
      <input v-model="label" style="width:100%;margin:4px 0" />
      <div class="muted" style="margin:6px 0 2px">选择连续段：</div>
      <div v-for="s in batch.segments" :key="s.id" class="row"
           style="margin:3px 0">
        <input type="checkbox" :value="s.id" v-model.number="selectedSegs"
               style="transform:scale(1.2)" />
        <span>{{ s.code }}</span>
        <span class="muted mono">{{ new Date(s.start_ts).toISOString().slice(11,19) }}
          –{{ new Date(s.end_ts).toISOString().slice(11,19) }}</span>
      </div>
      <div class="row" style="margin-top:8px">
        <label class="muted">最大样本间隔(s)</label>
        <input v-model.number="maxGap" type="number" style="width:80px" />
      </div>
      <div class="row" style="margin-top:6px">
        <label class="muted">外推容差(s)</label>
        <input v-model.number="extrap" type="number" style="width:80px" />
      </div>
      <div class="error" v-if="err">{{ err }}</div>
      <button style="margin-top:10px" :disabled="!selectedSegs.length"
              @click="create">创建窗口</button>
      <div class="muted" style="margin-top:6px">
        调整窗口会使依赖的计算立即过期，旧作业与结果不再标记为当前。
      </div>
    </div>
  </div>
</template>
