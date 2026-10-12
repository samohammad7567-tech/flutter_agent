import 'dart:developer' as developer;

import 'package:flutter_bloc/flutter_bloc.dart';

/// Logs cubit transitions and errors in one place, so no cubit prints.
class AppBlocObserver extends BlocObserver {
  const AppBlocObserver();

  @override
  void onChange(BlocBase<Object?> bloc, Change<Object?> change) {
    super.onChange(bloc, change);
    developer.log('${bloc.runtimeType} -> ${change.nextState}', name: 'bloc');
  }

  @override
  void onError(BlocBase<Object?> bloc, Object error, StackTrace stackTrace) {
    developer.log(
      '${bloc.runtimeType} failed',
      name: 'bloc',
      error: error,
      stackTrace: stackTrace,
    );
    super.onError(bloc, error, stackTrace);
  }
}
