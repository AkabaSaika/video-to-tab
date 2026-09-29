<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { parseHash } from './lib/route.js'
import GuitarApp from './views/GuitarApp.vue'

// the piano page (and Verovio with it) is loaded only when it is first opened
const PianoApp = defineAsyncComponent(() => import('./views/PianoApp.vue'))

const page = ref(parseHash(location.hash).page)
const pianoOpened = ref(page.value === 'piano')
watch(page, (p) => p === 'piano' && (pianoOpened.value = true))

function onHashChange() {
  page.value = parseHash(location.hash).page
}
onMounted(() => window.addEventListener('hashchange', onHashChange))
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <main>
    <header class="top">
      <h1>Video → Tab</h1>
      <nav class="tabs">
        <button :class="{ on: page === 'guitar' }" @click="page = 'guitar'">吉他 Tab</button>
        <button :class="{ on: page === 'piano' }" @click="page = 'piano'">钢琴谱</button>
      </nav>
    </header>
    <!-- both pages stay mounted, so switching never loses the other page's work -->
    <GuitarApp v-show="page === 'guitar'" :active="page === 'guitar'" />
    <PianoApp v-if="pianoOpened" v-show="page === 'piano'" :active="page === 'piano'" />
  </main>
</template>

<style scoped>
.top { display: flex; align-items: center; gap: 24px; margin-bottom: 16px; flex-wrap: wrap; }
.top h1 { margin: 0; }
.tabs { display: flex; gap: 4px; }
.tabs button { border-radius: 6px; }
.tabs button.on { background: #1f2937; border-color: #1f2937; color: #fff; }
</style>
