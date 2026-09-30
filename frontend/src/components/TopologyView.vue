<script setup>
import { computed } from 'vue'

const props = defineProps({
  batch: Object,
  topologies: Array,
  payload: Object
})

// 固定展示布局（按节点类型自动布列）；不依赖图布局库
const POS = {
  RAW: { x: 60, y: 130 },
  SEP: { x: 320, y: 130 },
  T_CREAM: { x: 600, y: 60 },
  BLEND: { x: 600, y: 210 },
  OUT: { x: 880, y: 135 }
}
const TYPE_LABEL = {
  source: '入口', separator: '分离机', tank: '罐',
  blender: '调配机', sink: '出口'
}

const topology = computed(() => {
  if (!props.batch) return null
  return props.topologies.find(t => t.id === props.batch.topology_id)
})

const totals = computed(() => props.payload?.window_totals || null)
const identified = computed(() => props.payload?.status === 'identified')

const edges = computed(() => {
  if (!topology.value) return []
  return topology.value.definition.streams.map(s => {
    const a = POS[s.source] || { x: 100, y: 100 }
    const b = POS[s.sink] || { x: 800, y: 100 }
    const mx = (a.x + b.x) / 2
    const my = (a.y + b.y) / 2 - 14
    const t = totals.value?.mass_kg?.[s.id]
    const f = totals.value?.fat_kg?.[s.id]
    return { ...s, x1: a.x + 52, y1: a.y, x2: b.x - 52, y2: b.y,
             mx, my, mass: t, fat: f }
  })
})
</script>

<template>
  <div v-if="topology">
    <div class="row" style="justify-content:space-between">
      <h2 style="margin:0;text-transform:none;letter-spacing:0;color:var(--text)">
        {{ topology.name }}
      </h2>
      <span class="pill" :class="identified ? 'ok' :
        payload?.status==='underdetermined' ? 'bad' : 'warn'">
        {{ payload?.status || '尚未计算' }}
      </span>
    </div>
    <svg class="flow-svg" viewBox="0 0 960 280">
      <defs>
        <marker id="arrow" markerWidth="10" markerHeight="10"
                refX="8" refY="3" orient="auto">
          <path d="M0,0 L8,3 L0,6 Z" fill="#7fa8d4" />
        </marker>
      </defs>
      <g v-for="e in edges" :key="e.id">
        <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2"
              stroke="#7fa8d4" stroke-width="2" marker-end="url(#arrow)" />
        <text :x="e.mx" :y="e.my" fill="#cfe1f5" font-size="12"
              text-anchor="middle">{{ e.id }}</text>
        <text v-if="identified && e.mass != null"
              :x="e.mx" :y="e.my + 14" fill="#7fd4a8" font-size="11"
              text-anchor="middle">
          {{ e.mass.toFixed(1) }} kg / {{ (e.fat || 0).toFixed(1) }} 脂肪
        </text>
      </g>
      <g v-for="n in topology.definition.nodes" :key="n.id">
        <rect :x="(POS[n.id]?.x || 60)" :y="(POS[n.id]?.y || 120) - 28"
              width="104" height="56" rx="9"
              :fill="n.type==='tank' ? '#21344d' : '#1a2a3e'"
              stroke="#3a5678" />
        <text :x="(POS[n.id]?.x || 60) + 52"
              :y="(POS[n.id]?.y || 120) - 6"
              fill="#eaf2fb" font-size="12" text-anchor="middle">
          {{ n.name || n.id }}
        </text>
        <text :x="(POS[n.id]?.x || 60) + 52"
              :y="(POS[n.id]?.y || 120) + 12"
              fill="#8fa9c4" font-size="10" text-anchor="middle">
          {{ TYPE_LABEL[n.type] }}
        </text>
      </g>
    </svg>
    <div class="muted" v-if="identified">
      线上标注为当前窗口（全部选中段）累计总质量与总脂肪（kg）。
      欠定时不显示任何调和值，避免误读为唯一结果。
    </div>
  </div>
</template>
