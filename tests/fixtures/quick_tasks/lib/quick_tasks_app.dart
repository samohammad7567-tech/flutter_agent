import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:easy_localization/easy_localization.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'core/di/service_locator.dart';
import 'core/localization/lang_keys.dart';
import 'core/routing/app_router.dart';

class QuickTasksApp extends StatelessWidget {
  const QuickTasksApp({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AppPreferencesCubit>.value(
      value: getIt<AppPreferencesCubit>(),
      child: BlocBuilder<AppPreferencesCubit, AppPreferencesState>(
        builder: (BuildContext context, AppPreferencesState state) {
          return MaterialApp.router(
            title: LangKeys.appName.tr(),
            debugShowCheckedModeBanner: false,
            theme: AppTheme.light(),
            darkTheme: AppTheme.dark(),
            themeMode: state.themeMode,
            localizationsDelegates: context.localizationDelegates,
            supportedLocales: context.supportedLocales,
            locale: context.locale,
            routerConfig: AppRouter.router,
          );
        },
      ),
    );
  }
}
