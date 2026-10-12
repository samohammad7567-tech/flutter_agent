import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:get_it/get_it.dart';

import '../../features/tasks/data/data_source/tasks_data_source.dart';
import '../../features/tasks/data/repos/tasks_repo.dart';
import '../../features/tasks/presentation/cubit/tasks_cubit.dart';

final GetIt getIt = GetIt.instance;

/// Registered once from `main.dart`, before `runApp`.
///
/// Cubits are factories and everything below them is a lazy singleton — a
/// singleton cubit would keep the previous screen's state and emit after
/// `close()`.
Future<void> setupServiceLocator() async {
  // Preferences / cache, from corereusablepackage.
  final AppCacheService cache = await AppCacheService.init();
  getIt
    ..registerSingleton<AppCacheService>(cache)
    ..registerLazySingleton<PreferencesRepo>(() => PreferencesRepo(cache))
    ..registerLazySingleton<AppPreferencesCubit>(
      () => AppPreferencesCubit(getIt<PreferencesRepo>()),
    );

  // Tasks
  getIt
    ..registerFactory<TasksCubit>(() => TasksCubit(repo: getIt<TasksRepo>()))
    ..registerLazySingleton<TasksRepo>(
      () => TasksRepo(dataSource: getIt<TasksDataSource>()),
    )
    ..registerLazySingleton<TasksDataSource>(
      () => TasksDataSource(getIt<AppCacheService>()),
    );
}
