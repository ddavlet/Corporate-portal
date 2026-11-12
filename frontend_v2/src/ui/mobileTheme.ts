import type { ThemeConfig } from 'antd'

/**
 * Field text at 16 px: iOS Safari zooms the page into any field with smaller text and does not zoom back out.
 */
const FIELD_FONT_SIZE = 16

/**
 * antd tokens of the mobile layout (nested ConfigProvider of the phone branch; the desktop keeps the defaults):
 * 44 px controls for touch, 15 px body text, 16 px in every field.
 */
export const MOBILE_ANTD_THEME: ThemeConfig = {
  token: {
    controlHeight: 44,
    fontSize: 15,
  },
  components: {
    Input: {
      fontSize: FIELD_FONT_SIZE,
      inputFontSize: FIELD_FONT_SIZE,
      inputFontSizeLG: FIELD_FONT_SIZE,
      inputFontSizeSM: FIELD_FONT_SIZE,
    },
    InputNumber: { fontSize: FIELD_FONT_SIZE, inputFontSize: FIELD_FONT_SIZE },
    Select: { fontSize: FIELD_FONT_SIZE },
    DatePicker: { fontSize: FIELD_FONT_SIZE, inputFontSize: FIELD_FONT_SIZE },
    Mentions: { fontSize: FIELD_FONT_SIZE },
  },
}
