import {
  Autocomplete,
  createTheme,
  MultiSelect,
  NumberInput,
  Select,
  TagsInput,
  Textarea,
  TextInput,
} from '@mantine/core';

/** Default vertical gap between label and input for form controls. */
const LABEL_INPUT_GAP = 8;

const formInputLabelStyles = {
  label: {
    marginBottom: LABEL_INPUT_GAP,
  },
};

/**
 * App theme. Defines default styles for form inputs (label spacing) in one place
 * so all labels have consistent spacing without repeating styles per component.
 */
export const appTheme = createTheme({
  components: {
    TextInput: TextInput.extend({
      styles: formInputLabelStyles,
    }),
    Textarea: Textarea.extend({
      styles: formInputLabelStyles,
    }),
    Select: Select.extend({
      styles: formInputLabelStyles,
    }),
    MultiSelect: MultiSelect.extend({
      styles: formInputLabelStyles,
    }),
    Autocomplete: Autocomplete.extend({
      styles: formInputLabelStyles,
    }),
    TagsInput: TagsInput.extend({
      styles: formInputLabelStyles,
    }),
    NumberInput: NumberInput.extend({
      styles: formInputLabelStyles,
    }),
  },
});
