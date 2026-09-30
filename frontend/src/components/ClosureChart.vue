<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({ result: Object })
const el = ref(null)
const basis = ref('reconciled')

const rows = computed(() => {
  const c = props.result?.payload?.closure
  if (!c) return []
  if (basis.value === 'reconciled' && c.reconciled) return c.reconciled
  return (c.measured || []).filter(r => r.complete)
})

const traces = computed(() => {
  const labels = rows.value.map(r =>
    `${r.segment} · ${r.node} · ${r.metric === 'mass' ? '质量' : '脂肪'}`)
  const vals = rows.value.map(r => r.residual_kg)
  const colors = vals.map(v => Math.abs(v) < 1e-6 ? '#3ecf8e' : '#ef6b6b')
  return [{
    type: 'bar', x: labels, y: vals, marker: { color: colors },
    hovertemplate: '%{x}<br>残差 %{y:.6f} kg<extra></extra>'
  }]
})

function render() {
  if (!el.value) return
  const layout = {
    paper_bgcolor: '#0f1720', plot_bgcolor: '#0f1720',
    font: { color: '#cdd9e7', size: 11 },
    margin: { t: 10, l: 60, r: 10, b: 140 },
    yaxis: { title: '闭合残差 (kg)', zerolinecolor: '#3a5678' },
    xaxis: { tickangle: -35 },
    height: 360
  }
  Plotly.react(el.value, traces.value, layout,
    { responsive: true, displaylogo: false })
}

onMounted(render)
watch([rows, basis], render, { deep: true })

const maxAbs = computed(() =>
  rows.value.reduce((m, r) => Math.max(m, Math.abs(r.residual_kg)), 0))
</script>

<template>
  <div class="card">
    <div class="row" style="justify-content:space-between">
      <h2 style="margin:0;text-transform:none;letter-spacing:0">
        闭合残差（流入 − 流出 − 罐存量变化）
      </h2>
      <div class="row">
        <button class="ghost" :class="{active: basis==='reconciled'}"
                @click="basis='reconciled'"
                :disabled="!result.payload.closure?.reconciled">
          守恒调和后</button>
        <button class="ghost" @click="basis='measured'">测量原样</button>
      </div>
    </div>
    <div class="muted" style="margin:6px 0">
      最大绝对残差：<strong>{{ maxAbs.toExponential(2) }}</strong> kg
      <span v-if="basis==='measured'">
        （仅展示入射流全部有测量的节点；罐中间存量未测时该行被标记不完整）</span>
    </div>
    <div ref="el"></div>
  </div>
</template>

<style scoped>
button.active { background: var(--accent); color: #08131f; }
</style>
