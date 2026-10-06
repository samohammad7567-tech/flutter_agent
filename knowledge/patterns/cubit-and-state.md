# Pattern: cubit and state

Source: `bilhikma/lib/features/archive/presentation/cubit/`. This is the
reference every new cubit is modelled on.

## State

A `final class`, a status enum, nullable data, a nullable error key, and getters
that pre-chew the decisions so no widget has to.

```dart
part of 'archive_cubit.dart';

enum ArchiveStatus { initial, loading, success, failure, empty }

final class ArchiveState {
  const ArchiveState({
    this.status = ArchiveStatus.initial,
    this.selectedFilter = ArchiveFilter.audios,
    this.items,
    this.errorKey,
  });

  final ArchiveStatus status;
  final ArchiveFilter selectedFilter;
  final List<LessonModel>? items;
  final String? errorKey;

  bool get isLoading => status == ArchiveStatus.loading;
  bool get isFirstLoad => isLoading && items == null;
  bool get hasFailed => status == ArchiveStatus.failure && items == null;
  List<LessonModel> get visibleItems => items ?? const <LessonModel>[];

  ArchiveState copyWith({
    ArchiveStatus? status,
    ArchiveFilter? selectedFilter,
    List<LessonModel>? items,
    String? errorKey,
    bool clearError = false,
  }) => ArchiveState(
    status: status ?? this.status,
    selectedFilter: selectedFilter ?? this.selectedFilter,
    items: items ?? this.items,
    errorKey: clearError ? null : errorKey ?? this.errorKey,
  );
}
```

The decisions worth copying:

* **`items` is nullable, and that nullability carries meaning.** `null` is "never
  loaded", `[]` is "loaded and empty". `isFirstLoad` and `hasFailed` both depend
  on the difference, which is how a failed refresh keeps showing stale data
  instead of blanking the screen.
* **`visibleItems` never returns null**, so the widget has no branch to get wrong.
* **`clearError`** exists because `copyWith` cannot express "set this nullable
  field back to null" any other way.
* **`state` is a `part of` the cubit file**, so the pair is always read together.

## Cubit

```dart
class ArchiveCubit extends Cubit<ArchiveState> {
  ArchiveCubit({this.repo = const ArchiveRepo()}) : super(const ArchiveState()) {
    loadSavedItems();
  }

  final ArchiveRepo repo;

  Future<void> loadSavedItems() async {
    emit(state.copyWith(status: ArchiveStatus.loading));
    await _load();
  }

  Future<void> refresh() => _load();

  /// Each chip is its own request - the type is sent as `filter[type]`.
  Future<void> selectFilter(ArchiveFilter filter) async {
    if (filter == state.selectedFilter) return;

    emit(state.copyWith(selectedFilter: filter, status: ArchiveStatus.loading));
    await _load();
  }

  Future<void> _load() async { /* see rules/errors.md */ }
}
```

The decisions worth copying:

* **The constructor loads.** The screen does not call `load()` after creating it.
* **`refresh()` reuses `_load()` without emitting `loading`**, which is what keeps
  a pull-to-refresh from flashing a spinner over content already on screen.
* **`selectFilter` returns early when nothing changed**, so tapping the active
  chip costs no request.
* **The repo is injected with a `const` default**, so the cubit is constructible
  in a test without a locator.

## Checklist for a new cubit

- [ ] `final class` state with a status enum and `copyWith`
- [ ] nullable data, `clearError`, and getters the widget can use without branching
- [ ] `if (isClosed) return;` after every `await`, before every `emit`
- [ ] no `BuildContext`, no `Navigator`, no `ScaffoldMessenger`
- [ ] errors reduced to an `errorKey`, never a formatted message
