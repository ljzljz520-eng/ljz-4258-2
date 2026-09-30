<script setup>
import { onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'
const props = defineProps({ title:String, data:{type:Array, required:true}, layout:{type:Object, default:()=>({})} })
const el = ref()
function render() {
  if (el.value) Plotly.react(el.value, props.data, { autosize:true, margin:{t:36,r:24,b:48,l:56}, title:props.title, ...props.layout }, {responsive:true, displaylogo:false})
}
onMounted(render)
watch(() => props.data, render, {deep:true})
watch(() => props.layout, render, {deep:true})
</script>
<template><div ref="el" style="height:330px"></div></template>
