<template>
  <div
    class="feature-carousel"
    @mouseenter="pause"
    @mouseleave="resume"
    @touchstart.passive="onTouchStart"
    @touchend.passive="onTouchEnd"
  >
    <div class="feature-carousel__viewport" :class="{ 'feature-carousel__viewport--embedded': embedded }">
      <div
        class="feature-carousel__track"
        :style="{ transform: `translateX(-${activeIndex * 100}%)` }"
      >
        <div
          v-for="(slide, index) in slides"
          :key="slide.src"
          class="feature-carousel__slide"
          :aria-hidden="index !== activeIndex"
        >
          <img
            :src="slide.src"
            :alt="slide.alt"
            class="feature-carousel__image"
            width="1200"
            height="800"
            decoding="async"
            :loading="index === 0 ? 'eager' : 'lazy'"
          />
        </div>
      </div>
    </div>

    <div class="feature-carousel__dots" role="tablist" aria-label="功能介绍轮播">
      <button
        v-for="(_, index) in slides"
        :key="index"
        type="button"
        role="tab"
        class="feature-carousel__dot"
        :class="{ 'feature-carousel__dot--active': index === activeIndex }"
        :aria-label="`第 ${index + 1} 页`"
        :aria-selected="index === activeIndex"
        @click="goTo(index)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

export interface FeatureSlide {
  src: string
  alt: string
}

const props = withDefaults(defineProps<{
  slides: FeatureSlide[]
  interval?: number
  embedded?: boolean
}>(), {
  interval: 5000,
  embedded: false,
})

const activeIndex = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
let touchStartX = 0

function goTo(index: number) {
  activeIndex.value = index
  restartAutoPlay()
}

function next() {
  activeIndex.value = (activeIndex.value + 1) % props.slides.length
}

function startAutoPlay() {
  stopAutoPlay()
  if (props.slides.length <= 1) return
  timer = setInterval(next, props.interval)
}

function stopAutoPlay() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function restartAutoPlay() {
  stopAutoPlay()
  startAutoPlay()
}

function pause() {
  stopAutoPlay()
}

function resume() {
  startAutoPlay()
}

function onTouchStart(event: TouchEvent) {
  touchStartX = event.changedTouches[0]?.clientX ?? 0
}

function onTouchEnd(event: TouchEvent) {
  const delta = (event.changedTouches[0]?.clientX ?? 0) - touchStartX
  if (Math.abs(delta) < 40) return
  if (delta < 0) {
    goTo((activeIndex.value + 1) % props.slides.length)
  } else {
    goTo((activeIndex.value - 1 + props.slides.length) % props.slides.length)
  }
}

onMounted(startAutoPlay)
onBeforeUnmount(stopAutoPlay)
</script>

<style scoped>
.feature-carousel {
  width: 100%;
}

.feature-carousel__viewport {
  overflow: hidden;
  border-radius: 1rem;
  background: var(--color-card, #fff);
  box-shadow: 0 18px 48px rgba(0, 60, 140, 0.08);
}

.feature-carousel__viewport--embedded {
  border-radius: 0.75rem;
  background: transparent;
  box-shadow: none;
}

.feature-carousel__track {
  display: flex;
  transition: transform 0.55s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;
}

.feature-carousel__slide {
  flex: 0 0 100%;
  min-width: 0;
}

.feature-carousel__image {
  display: block;
  width: 100%;
  height: auto;
  user-select: none;
  -webkit-user-drag: none;
}

.feature-carousel__dots {
  display: flex;
  justify-content: center;
  gap: 0.625rem;
  margin-top: 1.25rem;
}

.feature-carousel__dot {
  width: 0.5rem;
  height: 0.5rem;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: var(--color-border, #c6c6c8);
  cursor: pointer;
  transition: width 0.3s ease, background-color 0.3s ease, opacity 0.3s ease;
}

.feature-carousel__dot:hover {
  opacity: 0.85;
}

.feature-carousel__dot--active {
  width: 1.5rem;
  background: var(--color-accent, #007aff);
}
</style>
