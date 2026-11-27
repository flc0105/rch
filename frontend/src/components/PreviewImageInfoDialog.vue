<template>
  <FileInfoDialog :visible="visible" title="Image Info" :has-info="Boolean(info)"
                  :sections="formatted" empty-description="No image info available" :monospace-values="false"
                  @update:visible="$emit('update:visible', $event)" />
</template>

<script>
import FileInfoDialog from './FileInfoDialog.vue'
export default {
  name: 'PreviewImageInfoDialog',
  components: { FileInfoDialog },

  props: {
    visible: {
      type: Boolean,
      default: false,
    },

    info: {
      type: Object,
      default: null,
    },
  },

  emits: ['update:visible'],

  computed: {
    formatted() {
      const formatted = this.formatPreviewImageInfo(this.info)
      return [['basic', 'Basic'], ['exif', 'EXIF'], ['other', 'Other']]
        .map(([key, title]) => ({ key, title, items: formatted[key] }))
        .filter(section => section.items.length)
    },
  },

  methods: {
    // 图片信息展示格式化逻辑归属在图片信息弹窗内。
    formatPreviewImageInfo(info) {
      if (!info || typeof info !== 'object') {
        return {
          basic: [],
          exif: [],
          other: [],
        }
      }

      const basicFieldOrder = [
        ['name', 'Name'],
        ['width', 'Width'],
        ['height', 'Height'],
        ['size', 'Dimensions'],
        ['format', 'Format'],
        ['mode', 'Color Mode'],
        ['file_size_bytes', 'File Size (Bytes)'],
        ['artifact_id', 'Artifact ID'],
      ]

      const exifFieldOrder = [
        ['make', 'Camera Make'],
        ['model', 'Camera Model'],
        ['lens_model', 'Lens Model'],
        ['datetime_original', 'Date Taken'],
        ['exposure_time', 'Exposure Time'],
        ['f_number', 'F Number'],
        ['iso', 'ISO'],
        ['focal_length', 'Focal Length'],
        ['color_space', 'Color Space'],
        ['software', 'Software'],
        ['user_comment', 'User Comment'],
      ]

      const usedKeys = new Set()
      const basic = []
      const exif = []
      const other = []

      basicFieldOrder.forEach(([key, label]) => {
        if (key in info) {
          basic.push({
            key,
            label,
            value: this.formatPreviewImageInfoValue(info[key]),
          })
          usedKeys.add(key)
        }
      })

      exifFieldOrder.forEach(([key, label]) => {
        if (key in info) {
          exif.push({
            key,
            label,
            value: this.formatPreviewImageInfoValue(info[key]),
          })
          usedKeys.add(key)
        }
      })

      Object.keys(info).forEach((key) => {
        if (usedKeys.has(key)) return

        other.push({
          key,
          label: key,
          value: this.formatPreviewImageInfoValue(info[key]),
        })
      })

      return {
        basic,
        exif,
        other,
      }
    },

    formatPreviewImageInfoValue(value) {
      if (value === null || value === undefined || value === '') return '-'
      if (Array.isArray(value)) return value.join(', ')

      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (e) {
          return String(value)
        }
      }

      return String(value)
    },
  },
}
</script>
