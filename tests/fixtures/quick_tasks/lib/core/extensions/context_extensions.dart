import 'package:easy_localization/easy_localization.dart';
import 'package:flutter/material.dart';

extension AppLocalizationContext on BuildContext {
  /// Translates a [LangKeys] constant. Never pass a raw string literal.
  String translate(String key, {Map<String, String>? args}) =>
      key.tr(namedArgs: args);
}
