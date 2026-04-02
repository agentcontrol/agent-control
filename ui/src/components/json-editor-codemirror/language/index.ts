export { applyTextEdit, computeAutoEdit, extractEvaluatorNames } from './auto-edits';
export {
  buildCodeMirrorInlineServerValidationErrorsExtension,
  buildCodeMirrorJsonExtensions,
  buildCodeMirrorRefactorLightbulbExtension,
  buildCodeMirrorStandaloneDebugExtensions,
  getCodeMirrorCompletionItems,
  setInlineServerValidationErrorsEffect,
  shouldTriggerEvaluatorNameCompletion,
  triggerRefactorActionsDropdown,
} from './extensions';
export {
  caretAfterPrettyJsonReplace,
  fixJsonCommas,
  normalizeOnBlur,
  tryFormat,
} from './format';
