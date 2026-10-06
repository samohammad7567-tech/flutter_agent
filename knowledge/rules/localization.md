# Localization: Arabic first, keys never raw

Arabic is the primary language. Every project carries
`assets/translations/ar.json`, `assets/translations/en.json`, and
`lib/core/localization/lang_keys.dart`.

## The rule

A translation key appears in exactly three places, and a raw string literal is
never one of them.

```dart
// lib/core/localization/lang_keys.dart
class LangKeys {
  LangKeys._();

  static const savedItems = 'saved_items';
}
```

```json
// assets/translations/ar.json        // assets/translations/en.json
{ "saved_items": "العناصر المحفوظة" }  { "saved_items": "Saved items" }
```

```dart
Text(LangKeys.savedItems.tr())
// or
Text(context.translate(LangKeys.savedItems))
```

## What is wrong

```dart
Text('saved_items'.tr())       // R7: raw key - nothing stops a typo
Text('Saved items')            // R7: hardcoded, never translated
context.translate('saved_items')  // R7: same problem, different spelling
```

The constant is not decoration. `'saved_itmes'.tr()` compiles, ships, and renders
the key itself to the user; `LangKeys.savedItmes` does not compile.

## Adding UI text

Three edits, always together, or the next `flutter_check` run reports the drift:

1. add the key to **both** JSON files,
2. add the constant to `LangKeys`,
3. use it in the UI.

`flutter_scaffold` does all three for a new feature. R8 checks that LangKeys,
`ar.json` and `en.json` describe the same key set — a key in `en.json` but not
`ar.json` is an error, and a key in the JSON with no LangKeys constant is a
warning.

## Exceptions that are not violations

Interpolated and non-linguistic strings are not UI copy and are left alone:

```dart
Text('$count')      // a number
Text('-')           // a separator
Text('2x')          // a playback-speed label
```

Checked by rules R7 and R8.
