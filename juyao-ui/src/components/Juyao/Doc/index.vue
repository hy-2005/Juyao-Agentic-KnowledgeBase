<template>
  <div>
    <svg-icon icon-class="question" @click="goto" />
  </div>
</template>

<script>
export default {
  name: 'JuyaoDoc',
  data() {
    return {
      url: 'http://doc.juyao.vip/juyao-vue'
    }
  },
  methods: {
    goto() {
      window.open(this.url)
    }
  }
}
</script>