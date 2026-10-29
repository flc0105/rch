// Register only the Element Plus components used by the Vue templates.
// Explicit registration is stable in both Vite development and production builds.
// Component styles are imported individually; no full Element Plus CSS or plugin install.
import {
  ElAlert,
  ElAutocomplete,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLink,
  ElOption,
  ElPagination,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
  ElTree,
  ElLoadingDirective,
} from 'element-plus'

import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/autocomplete/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/collapse/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/drawer/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/link/style/css'
import 'element-plus/es/components/pagination/style/css'
import 'element-plus/es/components/progress/style/css'
import 'element-plus/es/components/radio/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/skeleton/style/css'
import 'element-plus/es/components/slider/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/tree/style/css'

export function registerElementPlusComponents(app) {
  app.component('el-alert', ElAlert)
  app.component('el-autocomplete', ElAutocomplete)
  app.component('el-button', ElButton)
  app.component('el-checkbox', ElCheckbox)
  app.component('el-collapse', ElCollapse)
  app.component('el-collapse-item', ElCollapseItem)
  app.component('el-descriptions', ElDescriptions)
  app.component('el-descriptions-item', ElDescriptionsItem)
  app.component('el-dialog', ElDialog)
  app.component('el-drawer', ElDrawer)
  app.component('el-dropdown', ElDropdown)
  app.component('el-dropdown-item', ElDropdownItem)
  app.component('el-dropdown-menu', ElDropdownMenu)
  app.component('el-empty', ElEmpty)
  app.component('el-form', ElForm)
  app.component('el-form-item', ElFormItem)
  app.component('el-icon', ElIcon)
  app.component('el-input', ElInput)
  app.component('el-input-number', ElInputNumber)
  app.component('el-link', ElLink)
  app.component('el-option', ElOption)
  app.component('el-pagination', ElPagination)
  app.component('el-progress', ElProgress)
  app.component('el-radio', ElRadio)
  app.component('el-radio-button', ElRadioButton)
  app.component('el-radio-group', ElRadioGroup)
  app.component('el-select', ElSelect)
  app.component('el-skeleton', ElSkeleton)
  app.component('el-slider', ElSlider)
  app.component('el-switch', ElSwitch)
  app.component('el-tab-pane', ElTabPane)
  app.component('el-table', ElTable)
  app.component('el-table-column', ElTableColumn)
  app.component('el-tabs', ElTabs)
  app.component('el-tag', ElTag)
  app.component('el-tooltip', ElTooltip)
  app.component('el-tree', ElTree)
  app.directive('loading', ElLoadingDirective)
}
