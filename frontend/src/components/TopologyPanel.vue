<script setup>
import { ref } from 'vue'
import { api } from '../lib/api'
const props = defineProps({ segment:Object })
const emit = defineEmits(['changed'])
const nodes = ref([]), edges = ref([]), error = ref('')
const nodeForm = ref({code:'',name:'',node_type:'process',include_inventory:true})
const edgeForm = ref({code:'',name:'',source_node_id:null,target_node_id:null,cross_batch:false})
async function load() {
  nodes.value = await api.get(`/api/segments/${props.segment.id}/nodes`)
  edges.value = await api.get(`/api/segments/${props.segment.id}/edges`)
  if(nodes.value.length) { edgeForm.value.source_node_id ??= nodes.value[0].id; edgeForm.value.target_node_id ??= nodes.value[0].id }
}
async function addNode(){ try { await api.post(`/api/segments/${props.segment.id}/nodes`, nodeForm.value); await load(); emit('changed') } catch(e){error.value=e.message} }
async function addEdge(){ try { await api.post(`/api/segments/${props.segment.id}/edges`, edgeForm.value); await load(); emit('changed') } catch(e){error.value=e.message} }
if(props.segment) load()
defineExpose({load})
</script>
<template>
<div class="card">
  <h2>拓扑：罐底旧料与跨批回流同一方程</h2>
  <div v-if="error" class="notice">{{error}}</div>
  <div class="row">
    <input v-model="nodeForm.code" placeholder="节点代码">
    <input v-model="nodeForm.name" placeholder="节点名称">
    <select v-model="nodeForm.node_type"><option value="process">过程</option><option value="tank">罐</option><option value="source">源</option><option value="sink">汇</option></select>
    <label><input style="width:auto" type="checkbox" v-model="nodeForm.include_inventory">库存</label>
    <button @click="addNode">加节点</button>
  </div>
  <div class="row">
    <input v-model="edgeForm.code" placeholder="物流代码">
    <select v-model="edgeForm.source_node_id"><option v-for="n in nodes" :value="n.id">{{n.code}}</option></select>
    →
    <select v-model="edgeForm.target_node_id"><option v-for="n in nodes" :value="n.id">{{n.code}}</option></select>
    <label><input style="width:auto" type="checkbox" v-model="edgeForm.cross_batch">跨批</label>
    <button @click="addEdge">加物流</button>
  </div>
  <h3>节点</h3><table><thead><tr><th>代码</th><th>类型</th><th>库存</th></tr></thead><tbody>
  <tr v-for="n in nodes" :key="n.id"><td>{{n.code}}</td><td>{{n.node_type}}</td><td>{{n.include_inventory?'是':'否'}}</td></tr></tbody></table>
  <h3>物流（允许成环）</h3><table><thead><tr><th>代码</th><th>源</th><th>目标</th><th>跨批</th></tr></thead><tbody>
  <tr v-for="e in edges" :key="e.id"><td>{{e.code}}</td><td>{{e.source_node_id}}</td><td>{{e.target_node_id}}</td><td>{{e.cross_batch?'是':'否'}}</td></tr></tbody></table>
</div>
</template>
