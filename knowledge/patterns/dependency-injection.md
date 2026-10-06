# Pattern: dependency injection

Source: `bilhikma/lib/core/di/service_locator.dart`. GetIt, registered once in
`main.dart` before `runApp`.

## Registration

Cascade notation, one triple per feature, read bottom-up: a cubit depends on a
repo, which depends on a data source.

```dart
getIt
  ..registerFactory(() => LiveSessionsCubit(repo: getIt()))
  ..registerLazySingleton(() => LiveSessionsRepo(dataSource: getIt()))
  ..registerLazySingleton(LiveSessionsDataSource.new);

getIt
  ..registerLazySingleton(() => SecurityRepo(dataSource: getIt()))
  ..registerLazySingleton(SecurityDataSource.new);
```

## Which lifetime, and why

| Type | Registration | Reason |
|---|---|---|
| Cubit | `registerFactory` | A new instance per screen. A singleton cubit keeps the previous screen's state and emits after `close()`. |
| Repo | `registerLazySingleton` | Stateless delegation; one instance is enough. |
| Data source | `registerLazySingleton` | Holds the client/cache; one instance is the point. |

`registerFactory` for cubits is the rule that matters. Registering a cubit as a
singleton is the single most common cause of "state from the last time I opened
this screen" and of `emit` after close.

`DataSource.new` is passed as a tear-off where the constructor takes no required
arguments — shorter than `() => DataSource()` and identical in effect.

## Not everything goes in the locator

Cubits with per-instance arguments are constructed directly, because the locator
has nothing to supply the argument from:

```dart
BlocProvider<LessonsCubit>(
  create: (_) => LessonsCubit(categorySubjectId: subjectId),
  child: const LessonsBody(),
)
```

A cubit that takes only injected dependencies comes from the locator instead:

```dart
BlocProvider<ArchiveCubit>(
  create: (_) => getIt<ArchiveCubit>(),
  child: ...,
)
```

## App-wide cubits

Preferences and other genuinely global state are registered as singletons and
provided above the router with `BlocProvider.value`, never recreated per screen:

```dart
getIt..registerLazySingleton(AppPreferencesCubit.new);
```

```dart
BlocProvider.value(
  value: getIt<AppPreferencesCubit>(),
  child: BlocBuilder<AppPreferencesCubit, AppPreferencesState>(
    builder: (context, state) => MaterialApp.router(
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: state.themeMode,
      locale: context.locale,
      routerConfig: AppRouter.router,
    ),
  ),
)
```

## Order in main.dart

```dart
WidgetsFlutterBinding.ensureInitialized();
Bloc.observer = AppBlocObserver();
await EasyLocalization.ensureInitialized();
// Firebase.initializeApp() here, if the project uses it
setupServiceLocator();
runApp(EasyLocalization(child: const BilhikmaApp()));
```

`setupServiceLocator()` runs last, because data sources registered in it may read
configuration that the initialisers above put in place.
