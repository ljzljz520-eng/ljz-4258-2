<script setup>
import { computed, ref, watch } from 'vue'
import PlotChart from './PlotChart.vue'
import { api } from '../lib/api'
const props = defineProps({ segment:Object, refreshKey:Number })
const pre = ref(null), job = ref(null), current = ref(null), error = ref(''), engineer = ref('')
async function runPrecheck(){
  error.value=''; try { pre.value = await api.post(`/api/segments/${props.segment.id}/precheck`) } catch(e){error.value=e.message}
}
async function enqueue(){
  error.value=''; try { job.value = await api.post(`/api/segments/${props.segment.id}/jobs`) } catch(e){error.value=e.message}
}
async function pollCurrent(){
  try { current.value = await api.get(`/api/segments/${props.segment.id}/current-result`) }
  catch(e){ current.value = null }
}
async function sign(){
  try { await api.post(`/api/jobs/${current.value.job_id}/signoff`, {engineer:engineer.value}); await pollCurrent() }
  catch(e){ error.value=e.message }
}
const residualData = computed(() => {
  const rows = current.value?.result?.node_residuals || []
  return ['mass','fat_mass'].map(component => ({
    type:'bar', name:component === 'mass' ? '质量' : '脂肪',
    x: rows.filter(r => r.component === component).map(r => r.node),
    y: rows.filter(r => r.component === component).map(r => r.raw_closure_kg)
  }))
})
const variableData = computed(() => {
  const vars = current.value?.result?.variables || []
  const shown = vars.filter(v => v.raw !== null).slice(0, 30)
  return [
    {type:'bar', name:'原始测量', x:shown.map(v=>v.name), y:shown.map(v=>v.raw)},
    {type:'bar', name:'调整后', x:shown.map(v=>v.name), y:shown.map(v=>v.adjusted)}
  ]
})
watch(() => props.refreshKey, () => { pre.value=null; current.value=null })
</script>
<template>
<div class="card">
  <h2>可辨识性、闭合残差与签署</h2>
  <div v-if="error" class="notice">{{error}}</div>
  <div class="row"><button @click="runPrecheck">计算前可辨识性检查</button><button @click="enqueue">冻结输入并入队</button><button class="secondary" @click="pollCurrent">读取当前图</button></div>
  <div v-if="job" class="muted">任务 #{{job.id}}：{{job.status}}，输入 v{{job.input_version}}</div>
  <div v-if="pre" style="margin-top:10px">
    <span class="badge" :class="pre.identifiability.identified?'ok':'bad'">
      {{pre.identifiability.identified ? '可辨识' : '欠定，不生成唯一结果'}}
    </span>
    <span class="muted">rank {{pre.identifiability.rank}} / {{pre.identifiability.variables}}</span>
    <div v-if="!pre.identifiability.identified">
      <h3>缺失测量与允许区间</h3><pre>{{JSON.stringify(pre.identifiability.missing_measurement_sets,null,2)}}</pre>
    </div>
  </div>
  <PlotChart v-if="current" title="节点质量/脂肪闭合残差（kg）" :data="residualData" :layout="{barmode:'group'}"/>
  <PlotChart v-if="current" title="原始与调整后变量（kg）" :data="variableData"/>
  <div v-if="current">
    <h3>闭合摘要</h3><pre>{{JSON.stringify(current.result.closure_summary,null,2)}}</pre>
    <p class="notice">{{current.result.disclaimer}}</p>
    <div v-if="current.signoff">已签署：{{current.signoff.engineer}} / {{current.signoff.signature}}<br>输入摘要 {{current.signoff.input_summary}}</div>
    <div v-else><input v-model="engineer" placeholder="工程师姓名"><button @click="sign">签署冻结输入摘要与算法版本</button></div>
  </div>
</div>
</template>
