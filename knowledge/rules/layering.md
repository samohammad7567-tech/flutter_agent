# Layering: who is allowed to do what

There is no `domain/`, no `entities/`, no `use_cases/`, no `repo_interface/`.
A feature has exactly two halves.

```
lib/features/<feature>/
  data/
    data_source/   # the ONLY place that talks to a backend or to storage
    models/        # fromJson / toJson
    repos/         # delegation, nothing else
  presentation/
    cubit/         # every decision the screen makes
    refactor/      # body sections pulled out of a screen
    screens/       # 30-70 lines: create the cubit, render the body
    widgets/       # small dumb components
```

## The contract

| Layer | Owns | Must never |
|---|---|---|
| Screen | Creating the cubit, rendering the body | Hold `_build...` methods or layout logic |
| Widget / refactor | Displaying state, forwarding actions | Call Firestore/Supabase/SharedPreferences/Dio, filter lists, map errors |
| Cubit | Loading, refresh, filters, selected values, error keys, UI-ready data | Touch `BuildContext` or navigate |
| Data source | Backend calls, transactions, validation, normalisation, status transitions | Import anything from `presentation/` |
| Repo | Delegating to data sources | Contain branching, `try`, or any logic |
| Model | `fromJson` / `toJson`, Timestamp handling | — |

## Why the cubit may not hold a BuildContext

A cubit outlives any single widget and may emit after the widget is gone. Holding
a context is how you get "used a BuildContext across an async gap" at best and a
crash at worst. The cubit emits; the widget reacts.

```dart
// wrong - the cubit reaches into the widget tree
Future<void> save() async {
  await repo.save();
  Navigator.of(context).pop();           // R6
  ScaffoldMessenger.of(context).showSnackBar(...);
}

// right - the cubit emits, the screen listens
Future<void> save() async {
  await repo.save();
  if (isClosed) return;
  emit(state.copyWith(status: ProfileStatus.saved));
}
```

```dart
// in the screen
BlocListener<ProfileCubit, ProfileState>(
  listenWhen: (previous, current) => current.status == ProfileStatus.saved,
  listener: (context, state) => context.pop(),
  child: ...,
)
```

## Why `isClosed` appears after every await

Every `emit` that follows an `await` is guarded, because the user can leave the
screen mid-request and emitting on a closed cubit throws. This is not optional
style — it is in every cubit in the corpus.

```dart
final List<LessonModel> items = await repo.fetchSavedItems();
if (isClosed) return;
emit(state.copyWith(items: items));
```

## Why the repo stays empty

The repo exists so a cubit never names a data source, which keeps the data source
free to split, merge, or grow a cache without touching presentation. The moment a
repo grows an `if`, that decision has escaped the layer that owns it.

```dart
// right - the whole file
class ArchiveRepo {
  const ArchiveRepo({this.dataSource = const ArchiveDataSource()});

  final ArchiveDataSource dataSource;

  Future<List<LessonModel>> fetchSavedItems({ContentType? type}) =>
      dataSource.fetchSavedItems(type: type);
}
```

Checked by rules R1, R2, R5, R6, R9, R12.
