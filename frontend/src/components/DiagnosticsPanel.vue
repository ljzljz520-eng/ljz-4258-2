<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({ result: Object })
const svEl = ref(null)

const p = computed(() => props.result?.payload || {})
const under = computed(() => p.value.status === 'underdetermined')

const missing = computed(() => p.value.missing_measurements || [])
const intervals = computed(() =>
  p.value.allowed_intervals?.intervals || [])
const cycles = computed(() => p.value.cycles || [])
const audit = computed(() => p.value.audit || {})

const svTrace = computed(() => [{
  type: 'scatter', mode: 'lines+markers',
  x: (p.value.singular_values || []).map((_, i) => i + 1),
  y: p.value.singular_values || [],
  marker: { color: '#4ea1ff' },
  line: { color: '#4ea1ff' },
  name: '奇异值'
}])

function renderSV() {
  if (!svEl.value) return
  Plotly.react(svEl.value, svTrace.value, {
    paper_bgcolor: '#0f1720', plot_bgcolor: '#0f1720',
    font: { color: '#cdd9e7', size: 11 },
    margin: { t: 10, l: 60, r: 10, b: 40 },
    yaxis: { title: '约束矩阵奇异值', type: 'log', zerolinecolor: '#3a5678' },
    xaxis: { title: '序号' }, height: 220
  }, { responsive: true, displaylogo: false })
}

onMounted(renderSV)
watch(svTrace, renderSV, { deep: true })
</script>

<template>
  <div>
    <div class="card">
      <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
        可辨识性检查
      </h2>
      <div class="kv">
        <dt>状态</dt>
        <dd><span class="pill" :class="under ? 'bad' : 'ok'">
          {{ under ? '欠定（不生成唯一结果）' :
            p.status === 'identified' ? '满秩可辨识' : p.status }}</span></dd>
        <dt>秩 / 未知量</dt>
        <dd>{{ p.rank }} / {{ p.unknowns }}
          <span v-if="under">（自由度 {{ p.nullity }}）</span></dd>
      </div>
      <div ref="svEl" style="margin-top:10px"></div>
    </div>

    <div class="card" v-if="cycles.length">
      <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
        回流 / 成环
      </h2>
      <div v-for="(c, i) in cycles" :key="i" class="notice"
           :style="c.unmeasured_cycle ?
             'border-color:var(--bad);background:rgba(239,107,107,.08)' : ''">
        环：<span class="mono">{{ c.streams.join(' → ') }}</span><br />
        {{ c.consequence }}
      </div>
    </div>

    <div class="card" v-if="under">
      <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
        缺失测量建议
      </h2>
      <table>
        <thead><tr>
          <th>流</th><th>段</th><th>测量</th><th>秩增益</th>
          <th>计量通道</th><th>允许量程</th>
        </tr></thead>
        <tbody>
          <tr v-for="(m, i) in missing" :key="i">
            <td class="mono">{{ m.stream_id }}</td>
            <td>seg{{ m.segment_seq }}</td>
            <td>{{ m.metric === 'flow' ? '流量' : '脂肪' }}</td>
            <td>+{{ m.rank_gain }}</td>
            <td><span class="pill" :class="m.meter_installed ? 'ok' : 'warn'">
              {{ m.meter_installed ? '已装表，缺读数' : '需加装' }}</span></td>
            <td class="mono" v-if="m.allowed_range">
              {{ m.allowed_range.low }}–{{ m.allowed_range.high }}
              {{ m.allowed_range.unit }}</td>
            <td v-else class="muted">—</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card" v-if="under && intervals.length">
      <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
        自由变量允许区间（非唯一解）
      </h2>
      <div class="muted" style="margin-bottom:6px">
        {{ p.allowed_intervals.note }}</div>
      <table>
        <thead><tr><th>变量</th><th>最小值 kg</th><th>最大值 kg</th>
          <th>说明</th></tr></thead>
        <tbody>
          <tr v-for="(x, i) in intervals" :key="i">
            <td class="mono" style="text-align:left">{{ x.variable }}</td>
            <td>{{ x.min_kg }}</td>
            <td>{{ x.max_kg === null ? '∞（无界）' : x.max_kg }}</td>
            <td style="text-align:left" class="muted">
              {{ x.interpretation }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
        覆盖性与数据审计
      </h2>
      <div v-if="audit.range_switches?.length">
        <div class="muted">量程切换：</div>
        <div v-for="x in audit.range_switches" :key="x" class="mono"
             style="font-size:12px">{{ x }}</div>
      </div>
      <div v-if="audit.late_excluded_sample_ids?.length">
        <div class="muted" style="margin-top:6px">
          冻结后迟到样品（已排除，不进入本次结果）：</div>
        <span v-for="id in audit.late_excluded_sample_ids" :key="id"
              class="pill warn" style="margin-right:5px">#{{ id }}</span>
      </div>
      <div v-if="audit.coverage_notes?.length">
        <div class="muted" style="margin-top:6px">覆盖性问题：</div>
        <ul style="margin:4px 0;padding-left:18px;font-size:12px">
          <li v-for="(n, i) in audit.coverage_notes" :key="i">
            {{ n.stream_id }} / {{ n.segment }}：{{ n.reason }}</li>
        </ul>
      </div>
      <div v-if="!audit.range_switches?.length &&
                  !audit.late_excluded_sample_ids?.length &&
                  !audit.coverage_notes?.length" class="muted">
        无量程空档、无迟到样品、无覆盖缺口。
      </div>
    </div>
  </div>
</template>
