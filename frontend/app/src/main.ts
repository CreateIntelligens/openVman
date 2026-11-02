import { createApp } from 'vue'
import { installStaleChunkRecovery } from '@shared/staleChunkReload'
import Root from './Root.vue'

// 唯一的動態 import 是語音 VAD。展示機台不會自己重新整理，舊 chunk 不見後麥克風
// 會一直失敗到有人手動重載。
installStaleChunkRecovery()

createApp(Root).mount('#app')
