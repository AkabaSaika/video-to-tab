<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { parseHash } from './lib/route.js'
import GuitarApp from './views/GuitarApp.vue'

// the piano and drum pages (and Verovio with them) are loaded only when first opened
const PianoApp = defineAsyncComponent(() => import('./views/PianoApp.vue'))
const DrumsApp = defineAsyncComponent(() => import('./views/DrumsApp.vue'))

const page = ref(parseHash(location.hash).page)
const pianoOpened = ref(page.value === 'piano')
const drumsOpened = ref(page.value === 'drums')
watch(page, (p) => {
  if (p === 'piano') pianoOpened.value = true
  if (p === 'drums') drumsOpened.value = true
})

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
        <button :class="{ on: page === 'drums' }" @click="page = 'drums'">鼓谱</button>
      </nav>
    </header>
    <!-- the pages stay mounted, so switching never loses another page's work -->
    <GuitarApp v-show="page === 'guitar'" :active="page === 'guitar'" />
    <PianoApp v-if="pianoOpened" v-show="page === 'piano'" :active="page === 'piano'" />
    <DrumsApp v-if="drumsOpened" v-show="page === 'drums'" :active="page === 'drums'" />
  </main>
</template>

<style scoped>
.top { display: flex; align-items: center; gap: 24px; margin-bottom: 16px; flex-wrap: wrap; }
.top h1 { margin: 0; }
.tabs { display: flex; gap: 4px; }
.tabs button { border-radius: 6px; }
.tabs button.on { background: #1f2937; border-color: #1f2937; color: #fff; }
</style>
