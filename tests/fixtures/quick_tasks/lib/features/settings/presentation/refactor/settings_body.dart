import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:easy_localization/easy_localization.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';

class SettingsBody extends StatelessWidget {
  const SettingsBody({super.key});

  static const Map<ThemeMode, String> _themeLabels = <ThemeMode, String>{
    ThemeMode.system: LangKeys.themeSystem,
    ThemeMode.light: LangKeys.themeLight,
    ThemeMode.dark: LangKeys.themeDark,
  };

  static const Map<String, String> _localeLabels = <String, String>{
    'ar': LangKeys.languageArabic,
    'en': LangKeys.languageEnglish,
  };

  @override
  Widget build(BuildContext context) {
    final AppPreferencesCubit preferences = context.read<AppPreferencesCubit>();

    return BlocBuilder<AppPreferencesCubit, AppPreferencesState>(
      builder: (BuildContext context, AppPreferencesState state) {
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            SettingRow(
              icon: Icons.brightness_6_outlined,
              title: context.translate(LangKeys.theme),
              trailing: DropdownButton<ThemeMode>(
                value: state.themeMode,
                underline: const SizedBox.shrink(),
                onChanged: (ThemeMode? mode) {
                  if (mode != null) preferences.setThemeMode(mode);
                },
                items: _themeLabels.entries
                    .map(
                      (MapEntry<ThemeMode, String> entry) =>
                          DropdownMenuItem<ThemeMode>(
                            value: entry.key,
                            child: Text(context.translate(entry.value)),
                          ),
                    )
                    .toList(growable: false),
              ),
            ),
            const Divider(height: 24),
            SettingRow(
              icon: Icons.translate,
              title: context.translate(LangKeys.language),
              trailing: DropdownButton<String>(
                value: context.locale.languageCode,
                underline: const SizedBox.shrink(),
                onChanged: (String? code) {
                  if (code == null) return;
                  final Locale locale = Locale(code);
                  // easy_localization owns the delegate; the cubit owns the
                  // persisted choice, so both are told.
                  context.setLocale(locale);
                  preferences.setLocale(locale);
                },
                items: _localeLabels.entries
                    .map(
                      (MapEntry<String, String> entry) =>
                          DropdownMenuItem<String>(
                            value: entry.key,
                            child: Text(context.translate(entry.value)),
                          ),
                    )
                    .toList(growable: false),
              ),
            ),
          ],
        );
      },
    );
  }
}
