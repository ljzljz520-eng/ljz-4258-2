<script setup>
import { ref, watch } from 'vue'
import { api } from '../lib/api'
const props = defineProps({ segment:Object, nodes:Array, edges:Array })
const rows = ref([]), error = ref('')
const form = ref({target_type:'edge',target_id:null,metric:'mass_flow',value:1,unit:'kg/h',basis:'wet',uncertainty_type:'stddev',uncertainty_value:.01,period_start:'',period_end:'',range_code:''})
async function load(){ rows.value = await api.get(`/api/segments/${props.segment.id}/measurements`) }
watch(() => props.segment.id, load, {immediate:true})
async function submit(){
  error.value=''
  const targets = form.value.target_type==='edge' ? props.edges : props.nodes
  if(!form.value.target_id && targets[0]) form.value.target_id = targets[0].id
  const body = {...form.value, period_end: form.value.period_end || null, range_code: form.value.range_code || null}
  try { await api.post(`/api/segments/${props.segment.id}/measurements`, body); await load() }
  catch(e){ error.value=e.message }
}
</script>
<template>
<div class="card">
  <h2>测量：单位、干湿基、不确定度、量程</h2>
  <div v-if="error" class="notice">{{error}}</div>
  <div class="row">
    <select v-model="form.target_type"><option value="edge">物流</option><option value="node">节点库存</option></select>
    <select v-model="form.target_id"><option v-for="t in (form.target_type==='edge'?edges:nodes)" :value="t.id">{{t.code}}</option></select>
    <select v-model="form.metric">
      <option value="mass_flow">质量流量</option><option value="volume_flow">体积流量</option>
      <option value="density">密度点样</option><option value="fat_fraction">脂肪点样</option>
      <option value="solids_fraction">固形物点样</option><option value="mass">质量</option>
      <option value="fat_mass">脂肪质量</option>
    </select>
    <input v-model.number="form.value" style="max-width:110px" placeholder="值">
    <input v-model="form.unit" style="max-width:100px" placeholder="单位">
    <select v-model="form.basis"><option value="wet">湿基</option><option value="dry">干基</option></select>
    <select v-model="form.uncertainty_type"><option value="stddev">标准不确定度</option><option value="expanded_95">95%扩展</option><option value="absolute">绝对值</option><option value="relative">相对</option></select>
    <input v-model.number="form.uncertainty_value" style="max-width:110px" placeholder="u">
    <input type="datetime-local" v-model="form.period_start">
    <input type="datetime-local" v-model="form.period_end" placeholder="点样留空">
    <input v-model="form.range_code" style="max-width:110px" placeholder="量程">
    <button @click="submit">提交测量</button>
  </div>
  <table><thead><tr><th>对象</th><th>指标</th><th>值/单位/基</th><th>不确定度</th><th>时间</th><th>量程</th></tr></thead><tbody>
    <tr v-for="m in rows" :key="m.id"><td>{{m.target_type}}:{{m.target_id}}</td><td>{{m.metric}}</td>
    <td>{{m.value}} {{m.unit}} / {{m.basis}}</td><td>{{m.uncertainty_type}} {{m.uncertainty_value}}</td>
    <td>{{new Date(m.period_start).toLocaleString()}}<span v-if="m.period_end"> → {{new Date(m.period_end).toLocaleString()}}</span></td>
    <td>{{m.range_code}}</td></tr>
  </tbody></table>
</div>
</template>
