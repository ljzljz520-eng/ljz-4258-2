<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({ windowId: Number, result: Object })
const emit = defineEmits(['signed'])

const engineer = ref('')
const note = ref('')
const signoffs = ref([])
const err = ref('')
const ok = ref('')

async function load() {
  if (!props.windowId) return
  try { signoffs.value = await api.signoffs(props.windowId) }
  catch (e) { signoffs.value = [] }
}

async function submit() {
  err.value = ''; ok.value = ''
  if (!props.result?.id) {
    err.value = '当前为试算视图或欠定结果；请等待 Worker 产出可签署的当前结果。'
    return
  }
  try {
    await api.signoff(props.result.id,
      { engineer: engineer.value, note: note.value })
    ok.value = '签署完成：输入摘要与算法版本已冻结（不可原地修改）。'
    engineer.value = ''; note.value = ''
    emit('signed')
    await load()
  } catch (e) { err.value = e.message }
}

onMounted(load)
watch(() => props.windowId, load)
</script>

<template>
  <div class="card">
    <h2 style="margin:0 0 8px;text-transform:none;letter-spacing:0">
      签署冻结
    </h2>
    <div class="notice">
      仅「满秩可辨识」的当前结果可签署。签署冻结输入摘要 SHA-256 与算法版本；
      后续样品或窗口变化生成新摘要，旧签署保持不变，只允许追加撤销事件。
    </div>

    <div class="kv" v-if="result">
      <dt>结果状态</dt>
      <dd>{{ result.status }}</dd>
      <dt>结果 ID</dt>
      <dd>{{ result.id ?? '（试算，未持久化）' }}</dd>
      <dt>输入摘要</dt>
      <dd class="mono">{{ result.digest }}</dd>
      <dt>算法版本</dt>
      <dd>{{ result.algorithm_version }}</dd>
    </div>

    <div class="row" style="margin-top:12px">
      <input v-model="engineer" placeholder="工程师签名" />
      <input v-model="note" placeholder="备注（可选）" style="flex:1" />
      <button @click="submit"
              :disabled="result.status !== 'identified'">签署</button>
    </div>
    <div class="error" v-if="err">{{ err }}</div>
    <div class="muted" v-if="ok" style="color:var(--ok);margin-top:6px">{{ ok }}</div>

    <h2 style="margin:18px 0 8px;text-transform:none;letter-spacing:0">
      历史签署（只追加）
    </h2>
    <table v-if="signoffs.length">
      <thead><tr><th>ID</th><th>工程师</th><th>摘要</th>
        <th>算法</th><th>状态</th><th>时间</th></tr></thead>
      <tbody>
        <tr v-for="s in signoffs" :key="s.id">
          <td>{{ s.id }}</td>
          <td>{{ s.engineer }}</td>
          <td class="mono">{{ s.input_digest.slice(0, 16) }}…</td>
          <td>{{ s.algorithm_version }}</td>
          <td><span class="pill" :class="s.revoked ? 'bad' : 'ok'">
            {{ s.revoked ? '已撤销（事件留痕）' : '有效' }}</span></td>
          <td>{{ new Date(s.created_at).toLocaleString() }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else class="muted">暂无签署。</div>
  </div>
</template>
