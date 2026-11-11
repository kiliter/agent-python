<!-- #Created By AiCoding(codex) 统一图标组件（集成 lucide-vue-next 开源图标与业务专属图标） -->
<script setup lang="ts">
import {
  FileText,
  BookOpen,
  Code2,
  Clock,
  ListChecks,
  GitBranch,
  Settings,
  Sun,
  Moon,
  Check,
  AlertTriangle,
  XCircle,
  Copy,
  Play,
  GripVertical,
  Crosshair,
  Quote,
  ArrowRightToLine,
  GitFork
} from 'lucide-vue-next'

defineProps<{
  name:
    | 'quote'
    | 'input'
    | 'derive'
    | 'template'
    | 'skill'
    | 'api'
    | 'run'
    | 'regression'
    | 'release'
    | 'settings'
    | 'sun'
    | 'moon'
    | 'check'
    | 'warn'
    | 'error'
    | 'copy'
    | 'play'
    | 'drag'
    | 'locate'
    | string
  size?: number
}>()
</script>

<template>
  <span class="inline-icon" style="display: inline-flex; align-items: center; justify-content: center; vertical-align: middle;">
    <Quote v-if="name === 'quote'" :size="size || 12" :stroke-width="1.85" />
    <ArrowRightToLine v-else-if="name === 'input'" :size="size || 12" :stroke-width="1.85" />
    <GitFork v-else-if="name === 'derive'" :size="size || 12" :stroke-width="1.85" />
    <FileText v-else-if="name === 'template'" :size="size || 15" :stroke-width="1.85" />
    <BookOpen v-else-if="name === 'skill'" :size="size || 15" :stroke-width="1.85" />
    <Code2 v-else-if="name === 'api'" :size="size || 15" :stroke-width="1.85" />
    <Clock v-else-if="name === 'run'" :size="size || 15" :stroke-width="1.85" />
    <ListChecks v-else-if="name === 'regression'" :size="size || 15" :stroke-width="1.85" />
    <GitBranch v-else-if="name === 'release'" :size="size || 15" :stroke-width="1.85" />
    <Settings v-else-if="name === 'settings'" :size="size || 15" :stroke-width="1.85" />
    <Sun v-else-if="name === 'sun'" :size="size || 14" :stroke-width="1.85" />
    <Moon v-else-if="name === 'moon'" :size="size || 14" :stroke-width="1.85" />
    <Check v-else-if="name === 'check'" :size="size || 13" :stroke-width="2" />
    <AlertTriangle v-else-if="name === 'warn'" :size="size || 13" :stroke-width="1.85" />
    <XCircle v-else-if="name === 'error'" :size="size || 13" :stroke-width="1.85" />
    <Copy v-else-if="name === 'copy'" :size="size || 12" :stroke-width="1.85" />
    <Play v-else-if="name === 'play'" :size="size || 12" :stroke-width="1.85" />
    <GripVertical v-else-if="name === 'drag'" :size="size || 13" :stroke-width="1.85" />
    <Crosshair v-else-if="name === 'locate'" :size="size || 12" :stroke-width="1.85" />
  </span>
</template>
