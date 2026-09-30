<script setup>
defineProps({ result: Object })
</script>

<template>
  <div>
    <h2 style="margin:0 0 10px;text-transform:none;letter-spacing:0">
      段 × 流 总量与调和值
    </h2>
    <table v-if="result.payload.stream_segments?.length">
      <thead><tr>
        <th>段</th><th>流</th>
        <th>测量质量 kg</th><th>σ kg</th>
        <th>调和质量 kg</th><th>测量脂肪 kg</th>
        <th>σ kg</th><th>调和脂肪 kg</th>
      </tr></thead>
      <tbody>
        <tr v-for="(r, i) in result.payload.stream_segments" :key="i">
          <td>{{ r.segment }}</td>
          <td class="mono">{{ r.stream_id }}</td>
          <td>{{ r.mass_measured_kg ?? '—' }}</td>
          <td>{{ r.mass_uc_kg ?? '—' }}</td>
          <td>{{ r.mass_reconciled_kg ?? '—' }}</td>
          <td>{{ r.fat_measured_kg ?? '—' }}</td>
          <td>{{ r.fat_uc_kg ?? '—' }}</td>
          <td>{{ r.fat_reconciled_kg ?? '—' }}</td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin:18px 0 10px;text-transform:none;letter-spacing:0">
      罐存量调和值（罐底旧料 / 跨段连续）
    </h2>
    <table v-if="result.payload.inventory_reconciled?.length">
      <thead><tr><th>节点</th><th>时点</th><th>段后</th>
        <th>质量 kg</th><th>脂肪 kg</th></tr></thead>
      <tbody>
        <tr v-for="(r, i) in result.payload.inventory_reconciled" :key="i">
          <td>{{ r.node }}</td>
          <td>{{ r.kind === 'middle' ? '段间' :
                r.kind === 'closing' ? '期末' : '期初' }}</td>
          <td>seg{{ r.segment_seq }}</td>
          <td>{{ r.mass_kg }}</td>
          <td>{{ r.fat_kg }}</td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin:18px 0 10px;text-transform:none;letter-spacing:0">
      窗口总量（手算核对入口）
    </h2>
    <pre class="mono" style="white-space:pre-wrap;font-size:12px">{{
      JSON.stringify(result.payload.window_totals, null, 2)
    }}</pre>
  </div>
</template>
