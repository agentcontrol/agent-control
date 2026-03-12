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

const LABEL_INPUT_GAP = 8;

const formInputLabelStyles = {
  label: {
    marginBottom: LABEL_INPUT_GAP,
  },
};

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
